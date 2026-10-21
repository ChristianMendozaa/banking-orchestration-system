"""Structured model output, and the citations that back a grounded answer.

These are the shapes `messages.parse` is asked to fill (`app.services.anthropic_provider`) -- see
`app.services.prompts`. They are separate from the kiosk request/response schemas
because nothing outside the AI path constructs them.
"""

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import (
    Category,
    ClarificationOutcome,
    ConfirmationIntent,
    ConsultationLevel,
    GroundingAttemptOutcome,
    GroundingCoverage,
)


class KnowledgeCitation(BaseModel):
    document_id: UUID
    chunk_id: UUID
    title: str
    section: str | None = None
    page: int
    source_url: str | None = None
    score: float = Field(ge=-1, le=1)


GROUNDED_ANSWER_MAX_CHARS = 1600
GROUNDED_SPOKEN_MAX_CHARS = 400
GROUNDING_GAP_MAX_CHARS = 300


def _clip_at_sentence(value: object, limit: int) -> object:
    """Structured outputs carry `max_length` to the model as a description, not as a decoding
    constraint, so a few characters over the limit used to fail validation and throw away a
    grounded answer as PROVIDER_ERROR (2026-10-21). Cut at the last sentence end that fits
    instead -- never mid-sentence, unless no sentence end fits at all."""
    if not isinstance(value, str) or len(value) <= limit:
        return value
    head = value[:limit]
    end = max(head.rfind(". "), head.rfind("? "), head.rfind("! "))
    return head[: end + 1] if end > 0 else head.rstrip()


class GroundedAnswerDecision(BaseModel):
    # The verdict comes first, before any answer text, so the answer is written to fit the
    # verdict rather than the verdict rationalising an answer already written. It is three
    # ways rather than a boolean because "documents and income are published, the credit
    # bureau is not" is neither supported nor unsupported, and a boolean made the model
    # throw the documented half away along with the gap.
    coverage: GroundingCoverage
    # What the evidence does not answer, when coverage is PARTIAL -- the answer says so out
    # loud, and the knowledge service refuses a PARTIAL that cannot name its own gap.
    missing: str | None = Field(default=None, max_length=GROUNDING_GAP_MAX_CHARS)
    answer: str = Field(min_length=1, max_length=GROUNDED_ANSWER_MAX_CHARS)
    # The same answer said out loud. A kiosk is a conversation, not a document: the full
    # `answer` belongs on screen and in the audit trail, and reading it aloud word for word
    # is what made the voice channel sound like a document reader. Both come out of the one
    # grounding call, so brevity costs no extra round trip and stays bound to the evidence.
    spoken: str = Field(min_length=1, max_length=GROUNDED_SPOKEN_MAX_CHARS)
    # Request-local ordinal references, never database identifiers. Asking a model to copy
    # UUIDs made a one-character transcription error turn an otherwise grounded answer into
    # INVALID_CITATIONS. The knowledge service maps these small integers back to the real
    # chunk IDs and remains the only authority that can construct a KnowledgeCitation.
    # Required, and after the answer: with a default it was optional in the schema, and
    # placed before the answer it came back empty on FULL verdicts (2026-10-21) -- the refs
    # are easiest to name once the sentences they support are written.
    cited_evidence_refs: list[int]

    @field_validator("missing", mode="before")
    @classmethod
    def _clip_missing(cls, value: object) -> object:
        return _clip_at_sentence(value, GROUNDING_GAP_MAX_CHARS)

    @field_validator("answer", mode="before")
    @classmethod
    def _clip_answer(cls, value: object) -> object:
        return _clip_at_sentence(value, GROUNDED_ANSWER_MAX_CHARS)

    @field_validator("spoken", mode="before")
    @classmethod
    def _clip_spoken(cls, value: object) -> object:
        return _clip_at_sentence(value, GROUNDED_SPOKEN_MAX_CHARS)

    @property
    def answers_something(self) -> bool:
        """Whether there is a grounded answer to give at all."""
        if self.coverage is GroundingCoverage.PARTIAL:
            return bool((self.missing or "").strip())
        return self.coverage is GroundingCoverage.FULL


class GroundedResponse(BaseModel):
    answer: str
    # Empty only for a response built before this field existed; callers fall back to
    # `answer`, which is what the voice channel used to receive in full.
    spoken: str = ""
    citations: list[KnowledgeCitation]


class GroundingAttempt(BaseModel):
    outcome: GroundingAttemptOutcome
    response: GroundedResponse | None = None
    diagnostics: dict = Field(default_factory=dict)


class ConfirmationReading(BaseModel):
    """What a reply to the confirmation question meant, read by the model.

    Only reached when the deterministic cue tables cannot settle it
    (`app.services.agents.rules.confirmation.unambiguous_confirmation`), so a plain "sí"
    still costs nothing. `corrected_request` is what makes "no, quería consultar los
    requisitos" usable without asking the person to say it all over again.
    """

    intent: ConfirmationIntent
    corrected_request: str | None = Field(default=None, max_length=400)
    # A concern raised alongside the answer -- "sí, y además no reconozco un cargo". Kept
    # separate so a yes does not swallow it and the security floors still see it.
    added_need: str | None = Field(default=None, max_length=400)


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
    # The turn with its references to the conversation resolved: "¿y los sábados?" becomes
    # "¿cuál es el horario de atención los sábados en esta sucursal?". Retrieval embeds this
    # instead of the fragment. It rides on the classification call that was already being
    # made, so context costs no additional round trip -- and it stays a *proposal*: the
    # backend still decides sensitivity, state and whether the turn may resolve at all.
    standalone_question: str | None = Field(default=None, max_length=400)
    # "Ya está, gracias, eso era todo": the person ends the conversation and asks nothing new.
    # Honoured only after the kiosk has already answered something in this session (see
    # `turn_nodes.route_ambiguity`); anywhere else the turn is classified as usual.
    closing_turn: bool = False
