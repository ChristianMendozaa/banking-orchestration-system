import re
from datetime import datetime
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_openai_provider, require_roles
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.models import KnowledgeChunk, KnowledgeDocument, User
from app.db.session import get_db
from app.domain.enums import (
    Category,
    KnowledgeIndexStatus,
    KnowledgeSourceType,
    UserRole,
)
from app.domain.schemas import (
    KnowledgeDocumentPage,
    KnowledgeDocumentSummary,
    KnowledgeDocumentUpdate,
    KnowledgeOperationResult,
)
from app.knowledge.management import KnowledgeManagementService, parse_json_list
from app.services.openai_provider import OpenAIProvider

router = APIRouter(prefix="/management/knowledge/documents", tags=["Conocimiento gerencial"])
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def get_management_service(
    settings: Settings = Depends(get_settings),
    provider: OpenAIProvider | None = Depends(get_openai_provider),
) -> KnowledgeManagementService:
    return KnowledgeManagementService(settings, provider)


async def require_document(db: AsyncSession, document_id: UUID) -> KnowledgeDocument:
    document = await db.get(KnowledgeDocument, document_id)
    if not document:
        raise AppError("KNOWLEDGE_DOCUMENT_NOT_FOUND", "Documento inexistente", 404)
    return document


async def document_summary(
    db: AsyncSession,
    document: KnowledgeDocument,
    *,
    chunk_count: int | None = None,
) -> KnowledgeDocumentSummary:
    if chunk_count is None:
        chunk_count = (
            await db.scalar(
                select(func.count(KnowledgeChunk.id)).where(
                    KnowledgeChunk.document_id == document.id
                )
            )
            or 0
        )
    categories = [Category(value) for value in document.metadata_json.get("categories", [])]
    return KnowledgeDocumentSummary(
        id=document.id,
        slug=document.slug,
        title=document.title,
        version=document.version,
        source_type=document.source_type,
        categories=categories,
        source_urls=list(document.source_urls),
        verified_at=document.verified_at,
        review_after=document.review_after,
        file_name=document.file_name,
        mime_type=document.mime_type,
        byte_size=document.byte_size,
        page_count=document.page_count,
        content_sha256=document.content_sha256,
        index_status=document.index_status,
        indexed_at=document.indexed_at,
        index_error=document.index_error,
        active=document.active,
        chunk_count=chunk_count,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def parse_categories(raw: str) -> list[Category]:
    values = parse_json_list(raw, "categories")
    try:
        return list(dict.fromkeys(Category(value) for value in values))
    except ValueError as exc:
        raise AppError("INVALID_CATEGORY", "Una categoria no es valida", 422) from exc


def parse_source_urls(raw: str) -> list[str]:
    values = parse_json_list(raw, "source_urls")
    if any(
        urlparse(value).scheme not in {"http", "https"} or not urlparse(value).netloc
        for value in values
    ):
        raise AppError(
            "INVALID_SOURCE_URL",
            "Las fuentes deben ser URL HTTP o HTTPS validas",
            422,
        )
    return values


@router.get("", response_model=KnowledgeDocumentPage)
async def list_documents(
    search: str | None = Query(default=None, max_length=120),
    active: bool | None = None,
    index_status: KnowledgeIndexStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_roles(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeDocumentPage:
    filters = []
    if search:
        term = f"%{search.strip()}%"
        filters.append(
            or_(
                KnowledgeDocument.title.ilike(term),
                KnowledgeDocument.slug.ilike(term),
                KnowledgeDocument.version.ilike(term),
            )
        )
    if active is not None:
        filters.append(KnowledgeDocument.active.is_(active))
    if index_status:
        filters.append(KnowledgeDocument.index_status == index_status)
    total = await db.scalar(select(func.count(KnowledgeDocument.id)).where(*filters)) or 0
    chunk_counts = (
        select(
            KnowledgeChunk.document_id.label("document_id"),
            func.count(KnowledgeChunk.id).label("chunk_count"),
        )
        .group_by(KnowledgeChunk.document_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                KnowledgeDocument,
                func.coalesce(chunk_counts.c.chunk_count, 0),
            )
            .outerjoin(chunk_counts, chunk_counts.c.document_id == KnowledgeDocument.id)
            .where(*filters)
            .order_by(KnowledgeDocument.slug, KnowledgeDocument.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    summaries = [
        await document_summary(db, document, chunk_count=int(chunk_count))
        for document, chunk_count in rows
    ]
    return KnowledgeDocumentPage(
        items=summaries,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", response_model=KnowledgeOperationResult, status_code=201)
async def create_document(
    file: UploadFile = File(...),
    slug: str = Form(..., min_length=3, max_length=160),
    title: str = Form(..., min_length=3, max_length=240),
    version: str = Form(..., min_length=1, max_length=40),
    source_type: KnowledgeSourceType = Form(...),
    categories: str = Form(...),
    source_urls: str = Form("[]"),
    verified_at: datetime = Form(...),
    review_after: datetime | None = Form(None),
    user: User = Depends(require_roles(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
    service: KnowledgeManagementService = Depends(get_management_service),
) -> KnowledgeOperationResult:
    normalized_slug = slug.strip().lower()
    if not SLUG_PATTERN.fullmatch(normalized_slug):
        raise AppError(
            "INVALID_SLUG",
            "El slug solo admite minusculas, numeros y guiones simples",
            422,
        )
    document, count = await service.create(
        db,
        upload=file,
        slug=normalized_slug,
        title=title.strip(),
        version=version.strip(),
        source_type=source_type,
        categories=parse_categories(categories),
        source_urls=parse_source_urls(source_urls),
        verified_at=verified_at,
        review_after=review_after,
        user_id=user.id,
    )
    await db.commit()
    await db.refresh(document)
    return KnowledgeOperationResult(
        document=await document_summary(db, document),
        indexed_chunks=count,
    )


@router.get("/{document_id}", response_model=KnowledgeDocumentSummary)
async def get_document(
    document_id: UUID,
    _: User = Depends(require_roles(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeDocumentSummary:
    return await document_summary(db, await require_document(db, document_id))


@router.patch("/{document_id}", response_model=KnowledgeDocumentSummary)
async def update_document(
    document_id: UUID,
    payload: KnowledgeDocumentUpdate,
    _: User = Depends(require_roles(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
    service: KnowledgeManagementService = Depends(get_management_service),
) -> KnowledgeDocumentSummary:
    document = await require_document(db, document_id)
    await service.patch(db, document, payload)
    await db.commit()
    await db.refresh(document)
    return await document_summary(db, document)


@router.delete("/{document_id}", status_code=204)
async def archive_document(
    document_id: UUID,
    _: User = Depends(require_roles(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
    service: KnowledgeManagementService = Depends(get_management_service),
) -> None:
    await service.archive(db, await require_document(db, document_id))
    await db.commit()


@router.post("/{document_id}/versions", response_model=KnowledgeOperationResult, status_code=201)
async def create_document_version(
    document_id: UUID,
    file: UploadFile = File(...),
    version: str = Form(..., min_length=1, max_length=40),
    verified_at: datetime = Form(...),
    review_after: datetime | None = Form(None),
    user: User = Depends(require_roles(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
    service: KnowledgeManagementService = Depends(get_management_service),
) -> KnowledgeOperationResult:
    source = await require_document(db, document_id)
    document, count = await service.create_version(
        db,
        source=source,
        upload=file,
        version=version.strip(),
        verified_at=verified_at,
        review_after=review_after,
        user_id=user.id,
    )
    await db.commit()
    await db.refresh(document)
    return KnowledgeOperationResult(
        document=await document_summary(db, document),
        indexed_chunks=count,
    )


@router.post("/{document_id}/reindex", response_model=KnowledgeOperationResult)
async def reindex_document(
    document_id: UUID,
    _: User = Depends(require_roles(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
    service: KnowledgeManagementService = Depends(get_management_service),
) -> KnowledgeOperationResult:
    document, count = await service.reindex(db, await require_document(db, document_id))
    await db.commit()
    await db.refresh(document)
    return KnowledgeOperationResult(
        document=await document_summary(db, document),
        indexed_chunks=count,
    )


@router.get("/{document_id}/download", response_class=FileResponse)
async def download_document(
    document_id: UUID,
    _: User = Depends(require_roles(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
    service: KnowledgeManagementService = Depends(get_management_service),
) -> FileResponse:
    document = await require_document(db, document_id)
    path = service.path_for(document)
    if not path.is_file():
        raise AppError("KNOWLEDGE_FILE_MISSING", "Archivo documental no disponible", 404)
    return FileResponse(path, media_type=document.mime_type, filename=document.file_name)
