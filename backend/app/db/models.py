from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import (
    CaseStatus,
    Category,
    ConsultationLevel,
    ConversationRole,
    ExecutiveStatus,
    GroundingStatus,
    IdentificationStatus,
    KnowledgeIndexStatus,
    KnowledgeJobOperation,
    KnowledgeJobStatus,
    KnowledgeSourceType,
    Priority,
    ResolutionOutcome,
    ResolutionType,
    SessionStatus,
    TicketStatus,
    UserRole,
)


def string_enum(enum_type: type) -> Enum:
    return Enum(enum_type, native_enum=False, validate_strings=True, length=40)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(string_enum(UserRole))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    executive_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("executives.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    executive: Mapped["Executive | None"] = relationship(back_populates="user")


class RefreshSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "refresh_sessions"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClientReference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "client_references"

    display_name: Mapped[str] = mapped_column(String(120))
    identifier_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    masked_identifier: Mapped[str] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Executive(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "executives"

    display_name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(120))
    window_number: Mapped[str] = mapped_column(String(40))
    status: Mapped[ExecutiveStatus] = mapped_column(
        string_enum(ExecutiveStatus), default=ExecutiveStatus.DISPONIBLE, index=True
    )
    last_assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    user: Mapped[User | None] = relationship(back_populates="executive", uselist=False)
    skills: Mapped[list["ExecutiveSkill"]] = relationship(
        back_populates="executive", cascade="all, delete-orphan"
    )


class ExecutiveSkill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "executive_skills"
    __table_args__ = (UniqueConstraint("executive_id", "category"),)

    executive_id: Mapped[UUID] = mapped_column(
        ForeignKey("executives.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[Category] = mapped_column(string_enum(Category), index=True)
    description: Mapped[str] = mapped_column(Text)
    experience_level: Mapped[int] = mapped_column(Integer, default=1)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    executive: Mapped[Executive] = relationship(back_populates="skills")


class KioskSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "kiosk_sessions"

    access_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[SessionStatus] = mapped_column(
        string_enum(SessionStatus), default=SessionStatus.CREATED, index=True
    )
    preferential_attention: Mapped[bool] = mapped_column(Boolean, default=False)
    clarification_count: Mapped[int] = mapped_column(Integer, default=0)
    correction_count: Mapped[int] = mapped_column(Integer, default=0)
    resolution_type: Mapped[ResolutionType | None] = mapped_column(
        string_enum(ResolutionType), nullable=True
    )
    final_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    grounding_status: Mapped[GroundingStatus] = mapped_column(
        string_enum(GroundingStatus), default=GroundingStatus.NOT_APPLICABLE
    )
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    requirements: Mapped[list["Requirement"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    case: Mapped["CaseRecord | None"] = relationship(
        back_populates="session", cascade="all, delete-orphan", uselist=False
    )
    conversation_messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.created_at",
    )


class ConversationMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint("session_id", "external_item_id"),
        Index("ix_conversation_messages_created_at", "created_at"),
    )

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("kiosk_sessions.id", ondelete="CASCADE"), index=True
    )
    external_item_id: Mapped[str] = mapped_column(String(160))
    role: Mapped[ConversationRole] = mapped_column(string_enum(ConversationRole), index=True)
    masked_text: Mapped[str] = mapped_column(Text)
    session: Mapped[KioskSession] = relationship(back_populates="conversation_messages")


class Requirement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "requirements"
    __table_args__ = (UniqueConstraint("session_id", "turn_id"),)

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("kiosk_sessions.id", ondelete="CASCADE"), index=True
    )
    turn_id: Mapped[UUID] = mapped_column(index=True)
    masked_text: Mapped[str] = mapped_column(Text)
    pii_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text)
    customer_summary: Mapped[str] = mapped_column(
        Text,
        server_default="Necesitas orientación sobre una consulta bancaria.",
    )
    confirmation_decision: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    category: Mapped[Category] = mapped_column(string_enum(Category), index=True)
    proposed_priority: Mapped[Priority] = mapped_column(string_enum(Priority), index=True)
    consultation_level: Mapped[ConsultationLevel] = mapped_column(
        string_enum(ConsultationLevel), index=True
    )
    confidence: Mapped[float] = mapped_column(Float)
    classification_source: Mapped[str] = mapped_column(String(20), default="FALLBACK")
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)
    clarification_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    force_human: Mapped[bool] = mapped_column(Boolean, default=False)
    urgency_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    security_incident: Mapped[bool] = mapped_column(Boolean, default=False)
    distress_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    session: Mapped[KioskSession] = relationship(back_populates="requirements")


class CaseRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cases"

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("kiosk_sessions.id", ondelete="CASCADE"), unique=True, index=True
    )
    requirement_id: Mapped[UUID] = mapped_column(
        ForeignKey("requirements.id", ondelete="RESTRICT"), unique=True
    )
    category: Mapped[Category] = mapped_column(string_enum(Category), index=True)
    priority: Mapped[Priority | None] = mapped_column(string_enum(Priority), index=True)
    consultation_level: Mapped[ConsultationLevel] = mapped_column(
        string_enum(ConsultationLevel), index=True
    )
    identification_status: Mapped[IdentificationStatus] = mapped_column(
        string_enum(IdentificationStatus), default=IdentificationStatus.ANONIMO
    )
    summary: Mapped[str] = mapped_column(Text)
    preferential_attention: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[CaseStatus] = mapped_column(
        string_enum(CaseStatus), default=CaseStatus.CREATED, index=True
    )
    force_human: Mapped[bool] = mapped_column(Boolean, default=False)
    session: Mapped[KioskSession] = relationship(back_populates="case")
    identification: Mapped["Identification | None"] = relationship(
        back_populates="case", cascade="all, delete-orphan", uselist=False
    )
    ticket: Mapped["Ticket | None"] = relationship(
        back_populates="case", cascade="all, delete-orphan", uselist=False
    )
    events: Mapped[list["TraceEvent"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="TraceEvent.created_at"
    )


class Identification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "identifications"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), unique=True, index=True
    )
    client_reference_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("client_references.id", ondelete="SET NULL"), nullable=True
    )
    identifier_hash: Mapped[str] = mapped_column(String(64))
    masked_identifier: Mapped[str] = mapped_column(String(32))
    identifier_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    identifier_nonce: Mapped[str | None] = mapped_column(String(32), nullable=True)
    identifier_key_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[IdentificationStatus] = mapped_column(string_enum(IdentificationStatus))
    case: Mapped[CaseRecord] = relationship(back_populates="identification")
    client_reference: Mapped[ClientReference | None] = relationship()


class Ticket(TimestampMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        Index(
            "uq_tickets_one_active_per_executive",
            "executive_id",
            unique=True,
            postgresql_where=text("status = 'EN_ATENCION'"),
            sqlite_where=text("status = 'EN_ATENCION'"),
        ),
    )

    number: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[UUID] = mapped_column(unique=True, index=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id", ondelete="CASCADE"), unique=True, index=True
    )
    executive_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("executives.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[TicketStatus] = mapped_column(
        string_enum(TicketStatus), default=TicketStatus.PENDIENTE, index=True
    )
    automatic: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_wait_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_outcome: Mapped[ResolutionOutcome | None] = mapped_column(
        string_enum(ResolutionOutcome), nullable=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    case: Mapped[CaseRecord] = relationship(back_populates="ticket")
    executive: Mapped[Executive | None] = relationship()


class TraceEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "trace_events"

    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    case: Mapped[CaseRecord] = relationship(back_populates="events")


class OperationalAuditEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "operational_audit_events"

    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str] = mapped_column(String(40), index=True)
    target_id: Mapped[str] = mapped_column(String(80), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


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


class KnowledgeGovernanceProposal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A CrewAI governance crew's review of a document, submitted for manager approval.

    Append-only: a proposal is never mutated or auto-applied. A manager who agrees with
    it acts through the existing `PATCH /management/knowledge/documents/{id}` endpoint
    (e.g. to change categories); this table is only the crew's recommendation and audit
    trail. Produced by the standalone `backend/governance` package, not by
    `KnowledgeWorker` -- CrewAI's dependency tree conflicts with the MCP server's, so it
    cannot run inside the main backend process. See backend/governance/README.md.
    """

    __tablename__ = "knowledge_governance_proposals"

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    category_suggestions: Mapped[list[str]] = mapped_column(JSON, default=list)
    section_suggestions: Mapped[list[str]] = mapped_column(JSON, default=list)
    review_after_suggestion: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    compliance_veto: Mapped[bool] = mapped_column(Boolean, default=False)
    compliance_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    compliance_notes: Mapped[str] = mapped_column(Text, default="")
    retrieval_qa_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    overall_recommendation: Mapped[str] = mapped_column(Text, default="")
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


Index("ix_tickets_executive_status", Ticket.executive_id, Ticket.status)
Index("ix_cases_category_priority", CaseRecord.category, CaseRecord.priority)
Index(
    "ix_knowledge_chunks_embedding_hnsw",
    KnowledgeChunk.embedding,
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
)
