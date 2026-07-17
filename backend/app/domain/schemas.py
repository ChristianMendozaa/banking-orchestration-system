from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.domain.enums import (
    Category,
    ConsultationLevel,
    GroundingStatus,
    IdentificationStatus,
    Priority,
    ResolutionType,
    SessionStatus,
    TicketStatus,
    UserRole,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserSummary(ORMModel):
    id: UUID
    email: EmailStr
    role: UserRole
    executive_id: UUID | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserSummary


class SessionCreateRequest(BaseModel):
    preferential_attention: bool = False


class SessionCreatedResponse(BaseModel):
    session_id: UUID
    session_token: str
    status: SessionStatus


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


class TurnAnalysisResponse(BaseModel):
    requirement_id: UUID
    status: SessionStatus
    summary: str
    category: Category
    consultation_level: ConsultationLevel
    confidence: float
    clarification_question: str | None = None
    pii_types: list[str] = Field(default_factory=list)
    next_action: Literal["CLARIFY", "CONFIRM"]
    speech_text: str


class ConfirmationRequest(BaseModel):
    confirmed: bool


class IdentificationRequest(BaseModel):
    identifier: str = Field(min_length=4, max_length=40)


class ExecutiveAssignment(BaseModel):
    id: UUID
    name: str
    title: str
    window_number: str


class TicketResult(BaseModel):
    id: UUID
    number: int
    status: TicketStatus


class FlowResult(BaseModel):
    session_id: UUID
    status: SessionStatus
    next_action: Literal["CAPTURE", "IDENTIFY", "COMPLETE"]
    identification_status: IdentificationStatus | None = None
    resolution_type: ResolutionType | None = None
    ticket: TicketResult | None = None
    executive: ExecutiveAssignment | None = None
    response: str | None = None
    speech_text: str
    tracking_information: str | None = None
    grounding_status: GroundingStatus = GroundingStatus.NOT_APPLICABLE
    citations: list["KnowledgeCitation"] = Field(default_factory=list)


class KnowledgeCitation(BaseModel):
    document_id: UUID
    chunk_id: UUID
    title: str
    section: str | None = None
    page: int
    source_url: str | None = None
    score: float = Field(ge=-1, le=1)


class GroundedAnswerDecision(BaseModel):
    answer: str = Field(min_length=1, max_length=1600)
    supported: bool
    cited_chunk_ids: list[UUID] = Field(default_factory=list)


class GroundedResponse(BaseModel):
    answer: str
    citations: list[KnowledgeCitation]


class SessionStatusResponse(BaseModel):
    session_id: UUID
    status: SessionStatus
    resolution_type: ResolutionType | None = None
    final_response: str | None = None
    result: FlowResult | None = None


class ClassificationDecision(BaseModel):
    summary: str = Field(min_length=5, max_length=500)
    category: Category
    consultation_level: ConsultationLevel
    confidence: float = Field(ge=0, le=1)
    ambiguous: bool
    clarification_question: str | None = Field(default=None, max_length=300)
    urgency_detected: bool = False
    security_incident: bool = False
    distress_detected: bool = False


class TraceEventOut(ORMModel):
    id: UUID
    event_type: str
    description: str
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_json")
    created_at: datetime


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
    identification_status: IdentificationStatus
    preferential_attention: bool
    version: int


class TicketPage(BaseModel):
    items: list[TicketListItem]
    page: int
    page_size: int
    total: int


class TicketDetail(TicketListItem):
    consultation_level: ConsultationLevel
    events: list[TraceEventOut]


class TicketStatusUpdate(BaseModel):
    status: TicketStatus
    expected_version: int = Field(ge=1)


class ManagerialCase(BaseModel):
    ticket: str
    category: Category
    priority: Priority
    executive: str | None
    status: TicketStatus
    attention_time_min: int | None
    created_at: datetime


class MetricSlice(BaseModel):
    name: str
    value: int


class HourlyMetric(BaseModel):
    hour: str
    cases: int


class ManagementMetrics(BaseModel):
    total_cases: int
    active_cases: int
    average_wait_minutes: float
    critical_pending: int
    by_category: list[MetricSlice]
    by_priority: list[MetricSlice]
    hourly: list[HourlyMetric]


class ManagementCasesResponse(BaseModel):
    items: list[ManagerialCase]
    page: int
    page_size: int
    total: int
