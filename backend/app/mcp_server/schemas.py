"""Output shapes for MCP tools.

Kept separate from `app.domain.schemas`: those models back the FastAPI OpenAPI contract
pinned by the `api-contract` CI job, and MCP tool payloads must be free to evolve without
touching that surface.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import (
    Category,
    ExecutiveStatus,
    IdentificationStatus,
    Priority,
    TicketStatus,
)


class KnowledgeSearchHit(BaseModel):
    chunk_id: UUID
    document_id: UUID
    title: str
    section: str | None = None
    page: int
    source_url: str | None = None
    score: float = Field(ge=-1, le=1)
    content: str


class KnowledgeSearchResult(BaseModel):
    query: str
    category: Category
    hits: list[KnowledgeSearchHit]


class TraceEventOut(BaseModel):
    event_type: str
    description: str
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class CaseTraceResult(BaseModel):
    case_id: UUID
    category: Category
    priority: Priority | None
    identification_status: IdentificationStatus
    status: str
    events: list[TraceEventOut]


class ExecutiveSkillOut(BaseModel):
    category: Category
    experience_level: int


class ExecutiveAvailabilityOut(BaseModel):
    executive_id: UUID
    display_name: str
    title: str
    status: ExecutiveStatus
    active_load: int
    skills: list[ExecutiveSkillOut]


class TicketStatusResult(BaseModel):
    ticket_id: UUID
    number: int
    status: TicketStatus
    automatic: bool
    priority: Priority | None
    estimated_wait_minutes: int | None
    executive_display_name: str | None
    executive_window_number: str | None
    created_at: datetime


class RoutingCandidateOut(BaseModel):
    executive_id: UUID
    display_name: str
    score: float
    semantic_score: float
    experience_score: float
    load_score: float
    active_load: int
    selected: bool


class RoutingExplanationOut(BaseModel):
    case_id: UUID
    category: Category
    candidates: list[RoutingCandidateOut]
    note: str | None = None
