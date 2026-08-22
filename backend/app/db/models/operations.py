"""What the orchestrator produced: the case, its identification, its ticket, and
the trace and audit events that explain both.

The only model module that imports its siblings, and it does so one way: nothing
in `identity` or `kiosk` imports back.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.columns import string_enum
from app.db.models.identity import ClientReference, Executive
from app.db.models.kiosk import KioskSession
from app.domain.enums import (
    CaseStatus,
    Category,
    ConsultationLevel,
    IdentificationStatus,
    Priority,
    ResolutionOutcome,
    TicketStatus,
)


class CaseRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "cases"

    # Not unique: a session can resolve one need automatically and then take another.
    # `tickets.case_id` stays unique below -- one ticket per case is still right, and a
    # second case brings its own.
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("kiosk_sessions.id", ondelete="CASCADE"), index=True
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
    session: Mapped[KioskSession] = relationship(back_populates="cases")
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


Index("ix_tickets_executive_status", Ticket.executive_id, Ticket.status)
Index("ix_cases_category_priority", CaseRecord.category, CaseRecord.priority)
