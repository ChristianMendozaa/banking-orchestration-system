import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from pypdf import PdfReader
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.domain.enums import (
    Category,
    KnowledgeIndexStatus,
    KnowledgeSourceType,
)
from app.domain.schemas import KnowledgeDocumentUpdate
from app.knowledge.indexing import (
    EmbeddingCountMismatchError,
    NoIndexableTextError,
    index_document,
)
from app.knowledge.repository import KnowledgeRepository
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

    async def create(
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
    ) -> tuple[KnowledgeDocument, int]:
        if not categories:
            raise AppError(
                "KNOWLEDGE_CATEGORIES_REQUIRED",
                "Seleccione al menos una categoria",
                422,
            )
        existing = await self.repository.current_document(db, slug, version)
        if existing:
            raise AppError(
                "KNOWLEDGE_VERSION_EXISTS",
                "Ya existe esa version para el documento",
                409,
            )
        path, content_hash, byte_size, page_count, original_name = await self._store_upload(upload)
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
            index_status=KnowledgeIndexStatus.INDEXING,
            created_by_user_id=user_id,
            active=False,
        )
        db.add(document)
        try:
            await db.flush()
            count = await self._index(db, document, path, categories)
            await self.repository.deactivate_other_versions(db, slug, document.id)
            document.active = True
            document.index_status = KnowledgeIndexStatus.READY
            document.indexed_at = datetime.now(UTC)
            document.index_error = None
            await db.flush()
            return document, count
        except Exception:
            await db.rollback()
            path.unlink(missing_ok=True)
            raise

    async def create_version(
        self,
        db: AsyncSession,
        *,
        source: KnowledgeDocument,
        upload: UploadFile,
        version: str,
        verified_at: datetime,
        review_after: datetime | None,
        user_id: UUID,
    ) -> tuple[KnowledgeDocument, int]:
        categories = [Category(value) for value in source.metadata_json.get("categories", [])]
        return await self.create(
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
        )

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
        document.active = False
        document.index_status = KnowledgeIndexStatus.ARCHIVED
        await db.flush()

    async def reindex(
        self, db: AsyncSession, document: KnowledgeDocument
    ) -> tuple[KnowledgeDocument, int]:
        path = self.path_for(document)
        if not path.is_file():
            raise AppError(
                "KNOWLEDGE_FILE_MISSING",
                "El archivo original del documento no esta disponible",
                409,
            )
        categories = [Category(value) for value in document.metadata_json.get("categories", [])]
        try:
            count = await self._index(db, document, path, categories)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                "KNOWLEDGE_INDEX_FAILED",
                "No fue posible reindexar el documento",
                502,
            ) from exc
        document.index_status = KnowledgeIndexStatus.READY
        document.indexed_at = datetime.now(UTC)
        document.index_error = None
        await db.flush()
        return document, count

    def path_for(self, document: KnowledgeDocument) -> Path:
        path = (self.storage_dir / document.storage_key).resolve()
        if path.parent != self.storage_dir:
            raise AppError("KNOWLEDGE_FILE_INVALID", "Ruta documental invalida", 500)
        return path

    async def _store_upload(self, upload: UploadFile) -> tuple[Path, str, int, int, str]:
        if upload.content_type not in {None, "application/pdf", "application/octet-stream"}:
            raise AppError("INVALID_PDF", "El archivo debe ser un PDF", 415)
        max_bytes = self.settings.knowledge_max_upload_mb * 1024 * 1024
        data = await upload.read(max_bytes + 1)
        if not data or len(data) > max_bytes:
            raise AppError(
                "PDF_TOO_LARGE",
                f"El PDF no debe superar {self.settings.knowledge_max_upload_mb} MB",
                413,
            )
        if not data.startswith(b"%PDF-"):
            raise AppError("INVALID_PDF", "El archivo no contiene una firma PDF valida", 422)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        storage_key = f"{uuid4()}.pdf"
        path = self.storage_dir / storage_key
        temporary = self.storage_dir / f".{storage_key}.tmp"
        temporary.write_bytes(data)
        try:
            reader = PdfReader(str(temporary))
            page_count = len(reader.pages)
            if page_count == 0 or page_count > self.settings.knowledge_max_pages:
                raise AppError(
                    "INVALID_PDF_PAGE_COUNT",
                    f"El PDF debe tener entre 1 y {self.settings.knowledge_max_pages} paginas",
                    422,
                )
            if not any((page.extract_text() or "").strip() for page in reader.pages):
                raise AppError(
                    "PDF_WITHOUT_TEXT",
                    "El PDF no contiene texto extraible para indexar",
                    422,
                )
            temporary.replace(path)
        except AppError:
            temporary.unlink(missing_ok=True)
            raise
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise AppError("INVALID_PDF", "No fue posible leer el PDF", 422) from exc
        original_name = Path(upload.filename or "documento.pdf").name[:255]
        return path, hashlib.sha256(data).hexdigest(), len(data), page_count, original_name

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


def parse_json_list(raw: str, field_name: str) -> list[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AppError("INVALID_FORM_FIELD", f"{field_name} debe ser JSON valido", 422) from exc
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise AppError("INVALID_FORM_FIELD", f"{field_name} debe ser una lista de textos", 422)
    return list(dict.fromkeys(item.strip() for item in value if item.strip()))
