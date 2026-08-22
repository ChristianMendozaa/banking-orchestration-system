"""Knowledge-corpus management schemas: documents, versions and indexing jobs."""

from datetime import datetime
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import (
    Category,
    KnowledgeIndexStatus,
    KnowledgeJobOperation,
    KnowledgeJobStatus,
    KnowledgeSourceType,
)
from app.domain.schemas.common import ORMModel


class KnowledgeDocumentSummary(BaseModel):
    id: UUID
    slug: str
    title: str
    version: str
    source_type: KnowledgeSourceType
    categories: list[Category]
    source_urls: list[str]
    verified_at: datetime
    review_after: datetime | None
    file_name: str
    mime_type: str
    byte_size: int
    page_count: int
    content_sha256: str
    index_status: KnowledgeIndexStatus
    indexed_at: datetime | None
    index_error: str | None
    active: bool
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentPage(BaseModel):
    items: list[KnowledgeDocumentSummary]
    page: int
    page_size: int
    total: int


class KnowledgeDocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=240)
    source_type: KnowledgeSourceType | None = None
    categories: list[Category] | None = None
    source_urls: list[str] | None = None
    verified_at: datetime | None = None
    review_after: datetime | None = None
    active: bool | None = None

    @field_validator("categories")
    @classmethod
    def require_categories(cls, value: list[Category] | None) -> list[Category] | None:
        if value is not None and not value:
            raise ValueError("Debe seleccionar al menos una categoria")
        return list(dict.fromkeys(value)) if value is not None else None

    @field_validator("source_urls")
    @classmethod
    def validate_source_urls(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if any(
            urlparse(item).scheme not in {"http", "https"} or not urlparse(item).netloc
            for item in normalized
        ):
            raise ValueError("Las fuentes deben ser URL HTTP o HTTPS validas")
        return normalized


class KnowledgeJobSummary(ORMModel):
    id: UUID
    document_id: UUID
    operation: KnowledgeJobOperation
    status: KnowledgeJobStatus
    attempts: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class KnowledgeJobResponse(BaseModel):
    job: KnowledgeJobSummary
    document: KnowledgeDocumentSummary
