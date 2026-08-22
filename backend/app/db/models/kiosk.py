"""One visit to the kiosk: the session, what was said in it, and the requirements
captured from it.

`KioskSession.cases` points at `operations.CaseRecord` by name rather than by
import -- SQLAlchemy resolves it through the declarative registry -- which is what
keeps this module free of a cycle with `operations`.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
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

if TYPE_CHECKING:  # `operations` imports this module, so the reverse must stay lazy.
    from app.db.models.operations import CaseRecord
from app.domain.enums import (
    Category,
    ConsultationLevel,
    ConversationRole,
    GroundingStatus,
    Priority,
    ResolutionType,
    SessionStatus,
)


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
    cases: Mapped[list["CaseRecord"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="CaseRecord.created_at",
    )
    conversation_messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.created_at",
    )

    @property
    def case(self) -> "CaseRecord | None":
        """The case this session is currently working on.

        A session used to own exactly one case, and most read paths still want "the one
        that matters now" -- the newest. A customer who asks a follow-up question after an
        automatic answer opens a second case (see `turn_nodes.guard_turn`), so the
        relationship is a list; this keeps the single-case readers honest instead of
        letting them index `[0]` and quietly read the wrong one.
        """
        return self.cases[-1] if self.cases else None


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
