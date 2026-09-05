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

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import (
    Category,
    ClarificationOutcome,
    ConfirmationKind,
    ConsultationLevel,
    ConversationRole,
    GroundingStatus,
    IdentificationStatus,
    IntentStatus,
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
    # Strings the model must reproduce word for word: an executive's name, the grounded
    # answer, the credential-entry warning. The client verifies these against a text
    # transcript of what was actually spoken, and deliberately only verifies the entries
    # a text comparison can settle -- Spanish speech renders "Ventanilla 3" as "ventanilla
    # tres", so anything carrying a digit is stated here and measured nowhere. See
    # `missingVerbatim` in `frontend/lib/kiosk-realtime.ts`.
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
    routing_category: Category | None = None
    intent_status: IntentStatus = IntentStatus.CONFIRMED
    confirmation_kind: ConfirmationKind = ConfirmationKind.INTENT
    clarification_outcome: ClarificationOutcome = ClarificationOutcome.NOT_APPLICABLE
    clarification_question: str | None = None
    pii_types: list[str] = Field(default_factory=list)
    next_action: Literal["CLARIFY", "CONFIRM", "DECLINE", "COMPLETE"]
    speech_text: str
    speech_plan: SpeechPlan
    result: "FlowResult | None" = None


class ConfirmationRequest(BaseModel):
    requirement_id: UUID
    # A hint, no longer the decision. The voice channel derives it from a cue table and the
    # text channel from an explicit button; either way the backend re-reads `transcript`
    # when there is one, because "sí, pero quiero consultar primero" and "claro, ¿qué
    # entendiste?" are not answers a boolean can carry -- and neither is a correction that
    # names what the person wanted instead.
    confirmed: bool | None = None
    # What the person actually said. Absent for the text channel's buttons, which are
    # unambiguous by construction.
    transcript: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def require_a_reading(self) -> "ConfirmationRequest":
        if self.confirmed is None and not (self.transcript or "").strip():
            raise ValueError("Se requiere `confirmed` o `transcript` para leer la respuesta")
        return self


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


class ConversationHistoryMessage(BaseModel):
    item_id: str
    role: ConversationRole
    text: str
    created_at: datetime


class ConversationHistoryResponse(BaseModel):
    messages: list[ConversationHistoryMessage]


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


class FlowOutcome(BaseModel):
    requirement_id: UUID
    need_index: int
    customer_summary: str
    category: Category
    priority: Priority | None = None
    identification_status: IdentificationStatus | None = None
    resolution_type: ResolutionType
    ticket: TicketResult | None = None
    executive: ExecutiveAssignment | None = None
    response: str | None = None
    grounding_status: GroundingStatus = GroundingStatus.NOT_APPLICABLE
    grounding_detail: dict[str, Any] = Field(default_factory=dict)
    citations: list[KnowledgeCitation] = Field(default_factory=list)


class FlowResult(BaseModel):
    session_id: UUID
    requirement_id: UUID
    status: SessionStatus
    # CONFIRM means nothing moved: the reply to the confirmation question was a question
    # of their own, or could not be read. The session is still AWAITING_CONFIRMATION and the
    # next reply belongs to `/confirmation`, not `/turns`.
    next_action: Literal["CAPTURE", "IDENTIFY", "COMPLETE", "CONFIRM"]
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
    grounding_detail: dict[str, Any] = Field(default_factory=dict)
    intent_status: IntentStatus = IntentStatus.CONFIRMED
    citations: list[KnowledgeCitation] = Field(default_factory=list)
    outcomes: list[FlowOutcome] = Field(default_factory=list)
    conversation_can_continue: bool = False
    remaining_turns: int = 0
    # Set only on a CAPTURE that came from a rejection which named what the person wanted
    # instead ("no, quería consultar los requisitos"). The client sends it straight through
    # `POST /turns` as the next turn, so the correction is used without being repeated. It
    # is the person's own words as the backend read them, never an invented request.
    corrected_request: str | None = None


class SessionStatusResponse(BaseModel):
    session_id: UUID
    status: SessionStatus
    resolution_type: ResolutionType | None = None
    final_response: str | None = None
    analysis: TurnAnalysisResponse | None = None
    result: FlowResult | None = None
