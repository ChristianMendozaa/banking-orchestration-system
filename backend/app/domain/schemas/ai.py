"""Structured model output, and the citations that back a grounded answer.

These are the shapes `responses.parse` is asked to fill -- see
`app.services.prompts`. They are separate from the kiosk request/response schemas
because nothing outside the AI path constructs them.
"""

from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import (
    Category,
    ConsultationLevel,
)


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
    out_of_scope: bool = False
