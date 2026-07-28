from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update

from app.db.models import KnowledgeDocument, KnowledgeJob
from app.domain.enums import KnowledgeJobOperation, KnowledgeJobStatus
from app.knowledge import worker as worker_module
from app.knowledge.worker import KnowledgeWorker
from tests.conftest import TestSession


async def _job(*, attempts: int, max_attempts: int = 3) -> KnowledgeJob:
    async with TestSession() as db:
        document = await db.scalar(select(KnowledgeDocument))
        assert document
        job = KnowledgeJob(
            document_id=document.id,
            operation=KnowledgeJobOperation.REINDEX,
            status=KnowledgeJobStatus.RUNNING,
            attempts=attempts,
            max_attempts=max_attempts,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job


async def test_worker_recovers_stale_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker_module, "SessionFactory", TestSession)
    recoverable = await _job(attempts=1)
    exhausted = await _job(attempts=3)
    stale = datetime.now(UTC) - timedelta(hours=1)
    async with TestSession() as db:
        await db.execute(
            update(KnowledgeJob)
            .where(KnowledgeJob.id.in_([recoverable.id, exhausted.id]))
            .values(updated_at=stale)
        )
        await db.commit()

    worker = KnowledgeWorker()
    await worker.recover_stale_jobs()

    async with TestSession() as db:
        recovered = await db.get(KnowledgeJob, recoverable.id)
        failed = await db.get(KnowledgeJob, exhausted.id)
        assert recovered and recovered.status == KnowledgeJobStatus.QUEUED
        assert recovered.started_at is None
        assert failed and failed.status == KnowledgeJobStatus.FAILED
        assert failed.error_code == "WORKER_INTERRUPTED"


async def test_worker_records_safe_failure_and_preserves_active_reindex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker_module, "SessionFactory", TestSession)
    job = await _job(attempts=1)
    worker = KnowledgeWorker()
    worker.service.process_job = AsyncMock(side_effect=RuntimeError("contenido sensible"))

    await worker.process(job.id)

    async with TestSession() as db:
        failed = await db.get(KnowledgeJob, job.id)
        document = await db.get(KnowledgeDocument, job.document_id)
        assert failed and failed.status == KnowledgeJobStatus.FAILED
        assert failed.error_code == "KNOWLEDGE_INDEX_FAILED"
        assert failed.error_message == "No fue posible completar la indexación"
        assert document and document.active is True
        assert document.index_error == failed.error_message


async def test_worker_run_stops_cleanly_after_an_idle_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker_module, "SessionFactory", TestSession)
    worker = KnowledgeWorker()
    worker.recover_stale_jobs = AsyncMock()

    async def stop_after_claim():
        worker.stop.set()
        return None

    worker.claim = AsyncMock(side_effect=stop_after_claim)
    await worker.run()

    worker.recover_stale_jobs.assert_awaited_once()
    worker.claim.assert_awaited_once()
