"""Structured outputs for the governance crew's tasks.

Deliberately independent of `backend/app/domain/schemas.py` -- this package has no
dependency on the `backend` project (see pyproject.toml docstring for why) and talks to
it only as an ordinary authenticated REST + MCP client. `GovernanceProposal.to_payload()`
is the one place that must stay in sync with the backend's `GovernanceProposalCreate`
request contract.
"""

from pydantic import BaseModel, Field

CATEGORIES = [
    "BLOQUEO_TARJETA",
    "REPORTE_FRAUDE",
    "CONSULTA_GENERAL",
    "SOLICITUD_CREDITO",
    "BANCA_DIGITAL",
]


class DocumentAnalysis(BaseModel):
    """Output of the Document Analyst task."""

    category_suggestions: list[str] = Field(
        default_factory=list,
        description=f"Subset of {CATEGORIES} this document's content actually supports.",
    )
    section_suggestions: list[str] = Field(
        default_factory=list, description="Proposed section headings found in the document."
    )
    review_after_suggestion: str | None = Field(
        default=None,
        description="ISO-8601 date by which this document should be reviewed again, if the "
        "content implies one (e.g. references a rate, fee, or policy likely to change).",
    )
    summary: str = Field(default="", description="One-paragraph summary of the document.")


class ComplianceReview(BaseModel):
    """Output of the Compliance Reviewer task. Can veto activation."""

    veto: bool = Field(
        description="True if this document must NOT be activated for customer-facing answers."
    )
    flags: list[str] = Field(
        default_factory=list,
        description="Specific concerns found: internal-only procedures, stale figures, "
        "anything resembling customer PII, unverifiable claims, etc.",
    )
    notes: str = Field(default="", description="Free-text compliance rationale.")


class RetrievalQAResult(BaseModel):
    question: str
    grounded: bool = Field(
        description="True if the retrieval tool returned evidence that "
        "actually answers the question."
    )
    notes: str = Field(default="")


class RetrievalQAReport(BaseModel):
    """Output of the Retrieval QA task."""

    results: list[RetrievalQAResult] = Field(default_factory=list)


class GovernanceProposal(BaseModel):
    """The crew's combined recommendation. Maps 1:1 onto the backend's
    `GovernanceProposalCreate` request body -- see `to_payload()`."""

    category_suggestions: list[str] = Field(default_factory=list)
    section_suggestions: list[str] = Field(default_factory=list)
    review_after_suggestion: str | None = None
    compliance_veto: bool = False
    compliance_flags: list[str] = Field(default_factory=list)
    compliance_notes: str = ""
    retrieval_qa_results: list[RetrievalQAResult] = Field(default_factory=list)
    overall_recommendation: str = ""

    @classmethod
    def from_task_outputs(
        cls,
        analysis: DocumentAnalysis,
        compliance: ComplianceReview,
        retrieval_qa: RetrievalQAReport,
    ) -> "GovernanceProposal":
        if compliance.veto:
            recommendation = "No activar: el revisor de cumplimiento vetó este documento."
        elif any(not result.grounded for result in retrieval_qa.results):
            recommendation = (
                "Revisar antes de activar: al menos una pregunta de prueba no encontró "
                "evidencia fundamentada."
            )
        else:
            recommendation = "Apto para activación segun el analisis automatizado."
        return cls(
            category_suggestions=[
                category for category in analysis.category_suggestions if category in CATEGORIES
            ],
            section_suggestions=analysis.section_suggestions,
            review_after_suggestion=analysis.review_after_suggestion,
            compliance_veto=compliance.veto,
            compliance_flags=compliance.flags,
            compliance_notes=compliance.notes,
            retrieval_qa_results=retrieval_qa.results,
            overall_recommendation=recommendation,
        )

    def to_payload(self) -> dict:
        """Body for `POST /management/knowledge/documents/{id}/governance-proposals`."""
        return {
            "category_suggestions": self.category_suggestions,
            "section_suggestions": self.section_suggestions,
            "review_after_suggestion": self.review_after_suggestion,
            "compliance_veto": self.compliance_veto,
            "compliance_flags": self.compliance_flags,
            "compliance_notes": self.compliance_notes,
            "retrieval_qa_results": [result.model_dump() for result in self.retrieval_qa_results],
            "overall_recommendation": self.overall_recommendation,
        }
