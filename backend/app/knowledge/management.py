from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import KnowledgeChunk, KnowledgeDocument, KnowledgeJob
from app.domain.enums import (
    Category,
    KnowledgeIndexStatus,
    KnowledgeJobOperation,
    KnowledgeJobStatus,
    KnowledgeSourceType,
)
from app.domain.schemas import KnowledgeDocumentUpdate
from app.knowledge.indexing import (
    EmbeddingCountMismatchError,
    NoIndexableTextError,
    index_document,
)
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.uploads import parse_json_list, store_upload
from app.services.openai_provider import OpenAIProvider


class KnowledgeManagementService:
    def __init__(
        self,
        settings: Settings,
        provider: OpenAIProvider | None,
        repository: KnowledgeRepository | None = None,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.repository = repository or KnowledgeRepository()
        self.storage_dir = Path(settings.knowledge_storage_dir).resolve()

    async def enqueue_create(
        self,
        db: AsyncSession,
        *,
        upload: UploadFile,
        slug: str,
        title: str,
        version: str,
        source_type: KnowledgeSourceType,
        categories: list[Category],
        source_urls: list[str],
        verified_at: datetime,
        review_after: datetime | None,
        user_id: UUID,
        operation: KnowledgeJobOperation = KnowledgeJobOperation.CREATE,
    ) -> tuple[KnowledgeDocument, KnowledgeJob]:
        if not categories:
            raise AppError(
                "KNOWLEDGE_CATEGORIES_REQUIRED",
                "Seleccione al menos una categoria",
                422,
            )
        if await self.repository.current_document(db, slug, version):
            raise AppError(
                "KNOWLEDGE_VERSION_EXISTS",
                "Ya existe esa version para el documento",
                409,
            )
        path, content_hash, byte_size, page_count, original_name = await store_upload(
            upload, self.settings, self.storage_dir
        )
        document = KnowledgeDocument(
            slug=slug,
            title=title,
            version=version,
            source_type=source_type,
            source_urls=source_urls,
            verified_at=verified_at,
            review_after=review_after,
            file_name=original_name,
            storage_key=path.name,
            mime_type="application/pdf",
            byte_size=byte_size,
            page_count=page_count,
            content_sha256=content_hash,
            metadata_json={"categories": [category.value for category in categories]},
            index_status=KnowledgeIndexStatus.PENDING,
            created_by_user_id=user_id,
            active=False,
        )
        db.add(document)
        try:
            await db.flush()
            job = KnowledgeJob(
                document_id=document.id,
                operation=operation,
                status=KnowledgeJobStatus.QUEUED,
                created_by_user_id=user_id,
            )
            db.add(job)
            await db.flush()
            return document, job
        except Exception:
            await db.rollback()
            path.unlink(missing_ok=True)
            raise

    async def enqueue_version(
        self,
        db: AsyncSession,
        *,
        source: KnowledgeDocument,
        upload: UploadFile,
        version: str,
        verified_at: datetime,
        review_after: datetime | None,
        user_id: UUID,
    ) -> tuple[KnowledgeDocument, KnowledgeJob]:
        categories = [Category(value) for value in source.metadata_json.get("categories", [])]
        return await self.enqueue_create(
            db,
            upload=upload,
            slug=source.slug,
            title=source.title,
            version=version,
            source_type=source.source_type,
            categories=categories,
            source_urls=list(source.source_urls),
            verified_at=verified_at,
            review_after=review_after,
            user_id=user_id,
            operation=KnowledgeJobOperation.VERSION,
        )

    async def enqueue_reindex(
        self,
        db: AsyncSession,
        *,
        document: KnowledgeDocument,
        user_id: UUID,
    ) -> KnowledgeJob:
        existing = await db.scalar(
            select(KnowledgeJob).where(
                KnowledgeJob.document_id == document.id,
                KnowledgeJob.status.in_([KnowledgeJobStatus.QUEUED, KnowledgeJobStatus.RUNNING]),
            )
        )
        if existing:
            raise AppError("KNOWLEDGE_JOB_ACTIVE", "El documento ya tiene un trabajo activo", 409)
        document.index_status = KnowledgeIndexStatus.INDEXING
        job = KnowledgeJob(
            document_id=document.id,
            operation=KnowledgeJobOperation.REINDEX,
            status=KnowledgeJobStatus.QUEUED,
            created_by_user_id=user_id,
        )
        db.add(job)
        await db.flush()
        return job

    async def process_job(
        self,
        db: AsyncSession,
        job: KnowledgeJob,
        document: KnowledgeDocument,
    ) -> int:
        path = self.path_for(document)
        if not path.is_file():
            raise AppError(
                "KNOWLEDGE_FILE_MISSING",
                "El archivo original del documento no está disponible",
                409,
            )
        categories = [Category(value) for value in document.metadata_json.get("categories", [])]
        count = await self._index(db, document, path, categories)
        if job.operation in {
            KnowledgeJobOperation.CREATE,
            KnowledgeJobOperation.VERSION,
        }:
            await self.repository.deactivate_other_versions(db, document.slug, document.id)
            document.active = True
        document.index_status = KnowledgeIndexStatus.READY
        document.indexed_at = datetime.now(UTC)
        document.index_error = None
        job.status = KnowledgeJobStatus.SUCCEEDED
        job.completed_at = datetime.now(UTC)
        job.error_code = None
        job.error_message = None
        await db.flush()
        return count

    async def patch(
        self,
        db: AsyncSession,
        document: KnowledgeDocument,
        payload: KnowledgeDocumentUpdate,
    ) -> KnowledgeDocument:
        data = payload.model_dump(exclude_unset=True)
        categories = data.pop("categories", None)
        active = data.pop("active", None)
        for field, value in data.items():
            setattr(document, field, value)
        if categories is not None:
            values = [category.value for category in categories]
            document.metadata_json = {**document.metadata_json, "categories": values}
            await db.execute(
                update(KnowledgeChunk)
                .where(KnowledgeChunk.document_id == document.id)
                .values(categories=values)
            )
        if active is not None:
            if active and document.index_status not in {
                KnowledgeIndexStatus.READY,
                KnowledgeIndexStatus.ARCHIVED,
            }:
                raise AppError(
                    "KNOWLEDGE_NOT_READY",
                    "Solo puede activarse un documento indexado",
                    409,
                )
            if active:
                await self.repository.deactivate_other_versions(db, document.slug, document.id)
                document.index_status = KnowledgeIndexStatus.READY
            else:
                document.index_status = KnowledgeIndexStatus.ARCHIVED
            document.active = active
        await db.flush()
        return document

    async def archive(self, db: AsyncSession, document: KnowledgeDocument) -> None:
        active_job = await db.scalar(
            select(KnowledgeJob).where(
                KnowledgeJob.document_id == document.id,
                KnowledgeJob.status.in_([KnowledgeJobStatus.QUEUED, KnowledgeJobStatus.RUNNING]),
            )
        )
        if active_job:
            raise AppError(
                "KNOWLEDGE_JOB_ACTIVE",
                "Espere a que termine el trabajo documental antes de archivar",
                409,
            )
        document.active = False
        document.index_status = KnowledgeIndexStatus.ARCHIVED
        await db.flush()

    def path_for(self, document: KnowledgeDocument) -> Path:
        path = (self.storage_dir / document.storage_key).resolve()
        if path.parent != self.storage_dir:
            raise AppError("KNOWLEDGE_FILE_INVALID", "Ruta documental invalida", 500)
        return path

    async def _index(
        self,
        db: AsyncSession,
        document: KnowledgeDocument,
        path: Path,
        categories: list[Category],
    ) -> int:
        if not self.provider:
            raise AppError(
                "OPENAI_NOT_CONFIGURED",
                "OpenAI es necesario para generar embeddings",
                503,
            )
        try:
            return await index_document(
                db,
                document=document,
                path=path,
                categories=categories,
                settings=self.settings,
                provider=self.provider,
                repository=self.repository,
            )
        except NoIndexableTextError as exc:
            raise AppError(
                "PDF_WITHOUT_INDEXABLE_TEXT",
                "El PDF no produjo fragmentos indexables",
                422,
            ) from exc
        except EmbeddingCountMismatchError as exc:
            raise AppError(
                "EMBEDDING_COUNT_MISMATCH",
                "La cantidad de embeddings no coincide con los fragmentos",
                502,
            ) from exc


# `parse_json_list` lives in `uploads` alongside the upload validation it belongs
# with, and is re-exported here because `app.api.knowledge` has always imported it
# from this module.
__all__ = ["KnowledgeManagementService", "parse_json_list"]
