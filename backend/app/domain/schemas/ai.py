"""Structured model output, and the citations that back a grounded answer.

These are the shapes `responses.parse` is asked to fill -- see
`app.services.prompts`. They are separate from the kiosk request/response schemas
because nothing outside the AI path constructs them.
"""

from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import (
    Category,
    ClarificationOutcome,
    ConsultationLevel,
    GroundingAttemptOutcome,
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
    # Request-local ordinal references, never database identifiers. Asking a model to copy
    # UUIDs made a one-character transcription error turn an otherwise grounded answer into
    # INVALID_CITATIONS. The knowledge service maps these small integers back to the real
    # chunk IDs and remains the only authority that can construct a KnowledgeCitation.
    cited_evidence_refs: list[int] = Field(default_factory=list)


class GroundedResponse(BaseModel):
    answer: str
    citations: list[KnowledgeCitation]


class GroundingAttempt(BaseModel):
    outcome: GroundingAttemptOutcome
    response: GroundedResponse | None = None
    diagnostics: dict = Field(default_factory=dict)


class ClassifiedNeed(BaseModel):
    summary: str = Field(min_length=5, max_length=500)
    customer_summary: str = Field(min_length=5, max_length=500)
    category: Category
    consultation_level: ConsultationLevel
    confidence: float = Field(ge=0, le=1)
    urgency_detected: bool = False
    security_incident: bool = False
    distress_detected: bool = False


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
    clarification_outcome: ClarificationOutcome = ClarificationOutcome.NOT_APPLICABLE
    additional_needs: list[ClassifiedNeed] = Field(default_factory=list)
