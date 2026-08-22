"""The approved corpus: documents, their embedded chunks, the jobs that index
them, and a record of every grounding attempt.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.columns import string_enum
from app.domain.enums import (
    KnowledgeIndexStatus,
    KnowledgeJobOperation,
    KnowledgeJobStatus,
    KnowledgeSourceType,
)


class KnowledgeDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (UniqueConstraint("slug", "version"),)

    slug: Mapped[str] = mapped_column(String(160), index=True)
    title: Mapped[str] = mapped_column(String(240))
    version: Mapped[str] = mapped_column(String(40))
    source_type: Mapped[KnowledgeSourceType] = mapped_column(
        string_enum(KnowledgeSourceType), index=True
    )
    source_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    file_name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    mime_type: Mapped[str] = mapped_column(String(100), default="application/pdf")
    byte_size: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    index_status: Mapped[KnowledgeIndexStatus] = mapped_column(
        string_enum(KnowledgeIndexStatus), default=KnowledgeIndexStatus.PENDING, index=True
    )
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    index_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KnowledgeChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("document_id", "ordinal"),)

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    page: Mapped[int] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(240), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    embedding_model: Mapped[str] = mapped_column(String(120))
    embedding: Mapped[list[float]] = mapped_column(Vector(1536))
    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")


class KnowledgeJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_jobs"

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    operation: Mapped[KnowledgeJobOperation] = mapped_column(
        string_enum(KnowledgeJobOperation), index=True
    )
    status: Mapped[KnowledgeJobStatus] = mapped_column(
        string_enum(KnowledgeJobStatus), default=KnowledgeJobStatus.QUEUED, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document: Mapped[KnowledgeDocument] = relationship()


class RAGInteraction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rag_interactions"

    case_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    masked_query: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(40), index=True)
    model: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(40))
    retrieved_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    answer_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)


Index(
    "ix_knowledge_chunks_embedding_hnsw",
    KnowledgeChunk.embedding,
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
)
