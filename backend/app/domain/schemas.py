import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.domain.enums import (
    Category,
    ConsultationLevel,
    ConversationRole,
    ExecutiveStatus,
    GroundingStatus,
    IdentificationStatus,
    KnowledgeIndexStatus,
    KnowledgeSourceType,
    Priority,
    ResolutionOutcome,
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
    next_action: Literal["CLARIFY", "CONFIRM"]
    speech_text: str


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
    analysis: TurnAnalysisResponse | None = None
    result: FlowResult | None = None


class ClassificationDecision(BaseModel):
    summary: str = Field(min_length=5, max_length=500)
    customer_summary: str = Field(min_length=5, max_length=500)
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


class ManagerialCase(BaseModel):
    id: UUID
    ticket: str
    summary: str
    category: Category
    priority: Priority
    executive: str | None
    status: TicketStatus
    attention_time_min: int | None
    wait_time_min: int
    resolution_outcome: ResolutionOutcome | None
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
    pending_cases: int
    in_attention_cases: int
    closed_cases: int
    average_wait_minutes: float
    average_attention_minutes: float
    critical_pending: int
    by_category: list[MetricSlice]
    by_priority: list[MetricSlice]
    hourly: list[HourlyMetric]
    executives: list["ExecutiveWorkload"]


class ExecutiveWorkload(BaseModel):
    id: UUID
    name: str
    title: str
    status: ExecutiveStatus
    pending: int
    in_attention: int
    closed: int


class ManagementCasesResponse(BaseModel):
    items: list[ManagerialCase]
    page: int
    page_size: int
    total: int


class PublicSystemConfig(BaseModel):
    app_name: str
    bank_name: str
    branch_name: str
    dashboard_refresh_ms: int


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


class KnowledgeOperationResult(BaseModel):
    document: KnowledgeDocumentSummary
    indexed_chunks: int
