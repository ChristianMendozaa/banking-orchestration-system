"""Everything the kiosk surface exchanges with the backend.

`SpeechPlan` is the contract with the voice model: `facts` may be reworded,
`verbatim` may not, `guidance` says what to do with them, and `fallback_text` is
the written rendering for the text channel. It is built in
`app.services.orchestrator.speech`.
"""

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import (
    Category,
    ConsultationLevel,
    ConversationRole,
    GroundingStatus,
    IdentificationStatus,
    Priority,
    ResolutionType,
    SessionStatus,
    TicketStatus,
)
from app.domain.schemas.ai import KnowledgeCitation


class SessionCreateRequest(BaseModel):
    preferential_attention: bool = False


class SessionCreatedResponse(BaseModel):
    session_id: UUID
    session_token: str
    status: SessionStatus
    expires_at: datetime


class RealtimeTokenResponse(BaseModel):
    value: str
    expires_at: int | None = None
    session: dict[str, Any] | None = None


class TurnRequest(BaseModel):
    turn_id: UUID
    transcript: str = Field(min_length=2, max_length=4000)
    is_clarification: bool = False

    @field_validator("transcript")
    @classmethod
    def clean_transcript(cls, value: str) -> str:
        return " ".join(value.split())


class SpeechPlan(BaseModel):
    """What the kiosk must convey on this step, and which parts of it are not the
    realtime model's to reword.

    The voice channel used to receive `speech_text` and be ordered to pronounce it
    literally, which made a conversational model an expensive text-to-speech engine. It
    now receives this instead: the facts the backend decided, one line of guidance, and
    the exact strings that carry operational or legal weight. Everything else -- greeting,
    acknowledgement, phrasing, register -- belongs to the model.

    `fallback_text` is the sentence `speech_text` carries, kept so the text channel and
    any client that cannot compose speech still have something correct to show.
    """

    intent: Literal["CLARIFY", "CONFIRM", "DECLINE", "CAPTURE", "IDENTIFY", "ANSWER", "HANDOFF"]
    facts: dict[str, str] = Field(default_factory=dict)
    # Strings the model must reproduce word for word: a ticket number, a window, an
    # executive's name, the grounded answer, the credential-entry warning. The client
    # verifies these against what was actually spoken.
    verbatim: list[str] = Field(default_factory=list)
    guidance: str
    fallback_text: str


class TurnAnalysisResponse(BaseModel):
    requirement_id: UUID
    status: SessionStatus
    summary: str
    customer_summary: str
    category: Category
    priority: Priority
    consultation_level: ConsultationLevel
    confidence: float
    clarification_question: str | None = None
    pii_types: list[str] = Field(default_factory=list)
    next_action: Literal["CLARIFY", "CONFIRM", "DECLINE", "COMPLETE"]
    speech_text: str
    speech_plan: SpeechPlan
    result: "FlowResult | None" = None


class ConfirmationRequest(BaseModel):
    requirement_id: UUID
    confirmed: bool


class IdentificationRequest(BaseModel):
    identifier: str = Field(min_length=4, max_length=16)

    @field_validator("identifier", mode="before")
    @classmethod
    def validate_ci(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().upper()
        if not re.fullmatch(r"\d{4,12}(?:-[A-Z]{1,3})?", normalized):
            raise ValueError(
                "El CI debe tener entre 4 y 12 dígitos y una extensión opcional, "
                "por ejemplo 6735666-SC"
            )
        return normalized


class ConversationMessageInput(BaseModel):
    item_id: str = Field(min_length=1, max_length=160)
    role: ConversationRole
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        return " ".join(value.split())


class ConversationSyncRequest(BaseModel):
    messages: list[ConversationMessageInput] = Field(min_length=1, max_length=100)


class ConversationSyncResponse(BaseModel):
    accepted: int


class ExecutiveAssignment(BaseModel):
    id: UUID
    name: str
    title: str
    window_number: str


class TicketResult(BaseModel):
    id: UUID
    number: int
    status: TicketStatus
    estimated_wait_minutes: int | None = None


class FlowResult(BaseModel):
    session_id: UUID
    requirement_id: UUID
    status: SessionStatus
    next_action: Literal["CAPTURE", "IDENTIFY", "COMPLETE"]
    customer_summary: str | None = None
    priority: Priority | None = None
    identification_status: IdentificationStatus | None = None
    resolution_type: ResolutionType | None = None
    ticket: TicketResult | None = None
    executive: ExecutiveAssignment | None = None
    response: str | None = None
    speech_text: str
    speech_plan: SpeechPlan
    tracking_information: str | None = None
    grounding_status: GroundingStatus = GroundingStatus.NOT_APPLICABLE
    citations: list[KnowledgeCitation] = Field(default_factory=list)


class SessionStatusResponse(BaseModel):
    session_id: UUID
    status: SessionStatus
    resolution_type: ResolutionType | None = None
    final_response: str | None = None
    analysis: TurnAnalysisResponse | None = None
    result: FlowResult | None = None
