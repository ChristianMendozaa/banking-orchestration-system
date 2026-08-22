"""Executive-facing ticket schemas: the queue, one ticket, and its transitions."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import (
    Category,
    ConsultationLevel,
    ConversationRole,
    IdentificationStatus,
    Priority,
    ResolutionOutcome,
    TicketStatus,
)
from app.domain.schemas.common import ORMModel


class TraceEventOut(ORMModel):
    id: UUID
    event_type: str
    description: str
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_json")
    created_at: datetime


class ConversationMessageOut(ORMModel):
    id: UUID
    role: ConversationRole
    text: str = Field(validation_alias="masked_text")
    created_at: datetime


class ProtectedIdentity(BaseModel):
    status: IdentificationStatus
    display_name: str | None = None
    masked_identifier: str | None = None
    reveal_available: bool = False


class TicketListItem(BaseModel):
    id: UUID
    number: str
    category: Category
    priority: Priority
    summary: str
    time_assigned: datetime | None
    minutes_elapsed: int
    executive_name: str | None
    executive_title: str | None
    window_number: str | None
    status: TicketStatus
    client_session_id: str
    wait_time_min: int
    estimated_wait_minutes: int | None
    identification_status: IdentificationStatus
    preferential_attention: bool
    client_display_name: str | None = None
    masked_identifier: str | None = None
    started_at: datetime | None = None
    closed_at: datetime | None = None
    resolution_outcome: ResolutionOutcome | None = None
    version: int


class TicketPage(BaseModel):
    items: list[TicketListItem]
    page: int
    page_size: int
    total: int
    status_counts: dict[TicketStatus, int]


class TicketDetail(TicketListItem):
    consultation_level: ConsultationLevel
    identity: ProtectedIdentity
    conversation: list[ConversationMessageOut]
    events: list[TraceEventOut]
    resolution_note: str | None = None


class TicketStatusUpdate(BaseModel):
    status: TicketStatus
    expected_version: int = Field(ge=1)
    resolution_outcome: ResolutionOutcome | None = None
    resolution_note: str | None = Field(default=None, min_length=10, max_length=1000)

    @field_validator("resolution_note")
    @classmethod
    def clean_resolution_note(cls, value: str | None) -> str | None:
        return " ".join(value.split()) if value is not None else None


class IdentifierRevealResponse(BaseModel):
    identifier: str
    reveal_seconds: int = 30
