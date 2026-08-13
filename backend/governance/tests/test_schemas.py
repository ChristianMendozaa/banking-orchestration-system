from crew.schemas import (
    ComplianceReview,
    DocumentAnalysis,
    GovernanceProposal,
    RetrievalQAReport,
    RetrievalQAResult,
)


def _analysis(**overrides: object) -> DocumentAnalysis:
    base = {
        "category_suggestions": ["CONSULTA_GENERAL", "BANCA_DIGITAL"],
        "section_suggestions": ["Horarios"],
        "review_after_suggestion": "2027-01-01",
        "summary": "Resumen de prueba.",
    }
    base.update(overrides)
    return DocumentAnalysis(**base)


def _compliance(**overrides: object) -> ComplianceReview:
    base = {"veto": False, "flags": [], "notes": "Sin hallazgos."}
    base.update(overrides)
    return ComplianceReview(**base)


def _qa(*results: RetrievalQAResult) -> RetrievalQAReport:
    return RetrievalQAReport(results=list(results))


def test_veto_produces_do_not_activate_recommendation() -> None:
    proposal = GovernanceProposal.from_task_outputs(
        _analysis(),
        _compliance(veto=True, flags=["procedimiento interno"]),
        _qa(),
    )
    assert proposal.compliance_veto is True
    assert "No activar" in proposal.overall_recommendation
    assert proposal.compliance_flags == ["procedimiento interno"]


def test_ungrounded_retrieval_produces_review_recommendation() -> None:
    proposal = GovernanceProposal.from_task_outputs(
        _analysis(),
        _compliance(),
        _qa(
            RetrievalQAResult(question="¿Horario?", grounded=True),
            RetrievalQAResult(question="¿Tasa vigente?", grounded=False, notes="Sin evidencia"),
        ),
    )
    assert proposal.compliance_veto is False
    assert "Revisar antes de activar" in proposal.overall_recommendation
    assert len(proposal.retrieval_qa_results) == 2


def test_clean_review_produces_positive_recommendation() -> None:
    proposal = GovernanceProposal.from_task_outputs(
        _analysis(),
        _compliance(),
        _qa(RetrievalQAResult(question="¿Horario?", grounded=True)),
    )
    assert proposal.compliance_veto is False
    assert "Apto para activaci" in proposal.overall_recommendation


def test_hallucinated_categories_are_dropped() -> None:
    proposal = GovernanceProposal.from_task_outputs(
        _analysis(category_suggestions=["CONSULTA_GENERAL", "CATEGORIA_INVENTADA"]),
        _compliance(),
        _qa(),
    )
    assert proposal.category_suggestions == ["CONSULTA_GENERAL"]


def test_to_payload_matches_backend_contract_shape() -> None:
    proposal = GovernanceProposal.from_task_outputs(
        _analysis(),
        _compliance(),
        _qa(RetrievalQAResult(question="¿Horario?", grounded=True, notes="ok")),
    )
    payload = proposal.to_payload()
    assert set(payload) == {
        "category_suggestions",
        "section_suggestions",
        "review_after_suggestion",
        "compliance_veto",
        "compliance_flags",
        "compliance_notes",
        "retrieval_qa_results",
        "overall_recommendation",
    }
    assert payload["retrieval_qa_results"] == [
        {"question": "¿Horario?", "grounded": True, "notes": "ok"}
    ]
