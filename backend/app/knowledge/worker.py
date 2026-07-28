import asyncio
import signal
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import KnowledgeDocument, KnowledgeJob
from app.db.session import SessionFactory
from app.domain.enums import (
    KnowledgeIndexStatus,
    KnowledgeJobOperation,
    KnowledgeJobStatus,
)
from app.knowledge.management import KnowledgeManagementService
from app.services.openai_provider import OpenAIProvider

logger = structlog.get_logger()


class KnowledgeWorker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.provider = OpenAIProvider(self.settings) if self.settings.openai_enabled else None
        self.service = KnowledgeManagementService(self.settings, self.provider)
        self.stop = asyncio.Event()

    async def recover_stale_jobs(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(minutes=15)
        async with SessionFactory() as db:
            await db.execute(
                update(KnowledgeJob)
                .where(
                    KnowledgeJob.status == KnowledgeJobStatus.RUNNING,
                    KnowledgeJob.updated_at < cutoff,
                    KnowledgeJob.attempts < KnowledgeJob.max_attempts,
                )
                .values(status=KnowledgeJobStatus.QUEUED, started_at=None)
            )
            await db.execute(
                update(KnowledgeJob)
                .where(
                    KnowledgeJob.status == KnowledgeJobStatus.RUNNING,
                    KnowledgeJob.updated_at < cutoff,
                    KnowledgeJob.attempts >= KnowledgeJob.max_attempts,
                )
                .values(
                    status=KnowledgeJobStatus.FAILED,
                    completed_at=datetime.now(UTC),
                    error_code="WORKER_INTERRUPTED",
                    error_message="El trabajo fue interrumpido y agotó sus intentos",
                )
            )
            await db.commit()

    async def claim(self) -> UUID | None:
        async with SessionFactory() as db:
            statement = (
                select(KnowledgeJob)
                .where(
                    KnowledgeJob.status == KnowledgeJobStatus.QUEUED,
                    KnowledgeJob.attempts < KnowledgeJob.max_attempts,
                )
                .order_by(KnowledgeJob.created_at)
                .limit(1)
            )
            if db.get_bind().dialect.name == "postgresql":
                statement = statement.with_for_update(skip_locked=True)
            job = await db.scalar(statement)
            if not job:
                return None
            job.status = KnowledgeJobStatus.RUNNING
            job.attempts += 1
            job.started_at = datetime.now(UTC)
            document = await db.get(KnowledgeDocument, job.document_id)
            if document:
                document.index_status = KnowledgeIndexStatus.INDEXING
            await db.commit()
            return job.id

    async def process(self, job_id: UUID) -> None:
        try:
            async with SessionFactory() as db:
                job = await db.get(KnowledgeJob, job_id)
                if not job or job.status != KnowledgeJobStatus.RUNNING:
                    return
                document = await db.get(KnowledgeDocument, job.document_id)
                if not document:
                    raise AppError(
                        "KNOWLEDGE_DOCUMENT_NOT_FOUND",
                        "Documento del trabajo inexistente",
                        404,
                    )
                count = await self.service.process_job(db, job, document)
                await db.commit()
                logger.info(
                    "knowledge_job_succeeded",
                    job_id=str(job.id),
                    document_id=str(document.id),
                    operation=job.operation.value,
                    indexed_chunks=count,
                )
        except Exception as exc:
            async with SessionFactory() as db:
                job = await db.get(KnowledgeJob, job_id)
                if not job:
                    return
                document = await db.get(KnowledgeDocument, job.document_id)
                job.status = KnowledgeJobStatus.FAILED
                job.completed_at = datetime.now(UTC)
                job.error_code = exc.code if isinstance(exc, AppError) else "KNOWLEDGE_INDEX_FAILED"
                job.error_message = (
                    exc.message
                    if isinstance(exc, AppError)
                    else "No fue posible completar la indexación"
                )
                if document:
                    if job.operation == KnowledgeJobOperation.REINDEX and document.active:
                        document.index_status = KnowledgeIndexStatus.READY
                    else:
                        document.index_status = KnowledgeIndexStatus.FAILED
                    document.index_error = job.error_message
                await db.commit()
                logger.exception(
                    "knowledge_job_failed",
                    job_id=str(job.id),
                    document_id=str(job.document_id),
                    operation=job.operation.value,
                    error_code=job.error_code,
                )

    async def run(self) -> None:
        await self.recover_stale_jobs()
        logger.info("knowledge_worker_started")
        while not self.stop.is_set():
            job_id = await self.claim()
            if job_id:
                await self.process(job_id)
                continue
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=2)
            except TimeoutError:
                pass
        logger.info("knowledge_worker_stopped")


async def main() -> None:
    worker = KnowledgeWorker()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, worker.stop.set)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
