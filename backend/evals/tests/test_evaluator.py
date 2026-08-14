from harness.client import SessionHandle
from harness.evaluator import Evaluator
from harness.session import ConversationSession


def _session(*, category=None, level=None, rounds=0) -> ConversationSession:
    session = ConversationSession(client=None, handle=SessionHandle("sid", "tok"))
    session.last_category = category
    session.last_consultation_level = level
    session.clarification_rounds = rounds
    return session


def test_fraud_must_reach_critical_priority() -> None:
    evaluator = Evaluator()
    session = _session(category="REPORTE_FRAUDE")
    result = evaluator.evaluate(
        persona_name="p",
        session=session,
        final_state={"status": "ASSIGNED", "result": {"priority": "ALTO"}},
    )
    check = next(c for c in result.checks if c.name == "fraud_reaches_critical")
    assert check.passed is False
    assert result.passed is False


def test_fraud_at_critical_passes() -> None:
    evaluator = Evaluator()
    session = _session(category="REPORTE_FRAUDE")
    result = evaluator.evaluate(
        persona_name="p",
        session=session,
        final_state={"status": "ASSIGNED", "result": {"priority": "CRITICO"}},
    )
    check = next(c for c in result.checks if c.name == "fraud_reaches_critical")
    assert check.passed is True


def test_non_fraud_check_is_not_applicable() -> None:
    evaluator = Evaluator()
    session = _session(category="CONSULTA_GENERAL")
    result = evaluator.evaluate(
        persona_name="p",
        session=session,
        final_state={"status": "RESOLVED_AUTOMATIC", "result": {}},
    )
    check = next(c for c in result.checks if c.name == "fraud_reaches_critical")
    assert check.passed is True
    assert "n/a" in check.detail


def test_clarifications_bounded_fails_over_limit() -> None:
    evaluator = Evaluator(max_clarifications=2)
    session = _session(rounds=3)
    result = evaluator.evaluate(persona_name="p", session=session, final_state={"result": {}})
    check = next(c for c in result.checks if c.name == "clarifications_bounded")
    assert check.passed is False


def test_sensitive_case_requires_resolved_identification() -> None:
    evaluator = Evaluator()
    session = _session(level="SENSIBLE")
    result = evaluator.evaluate(
        persona_name="p",
        session=session,
        final_state={"result": {"identification_status": "PENDIENTE"}},
    )
    check = next(c for c in result.checks if c.name == "sensitive_requires_identification")
    assert check.passed is False


def test_sensitive_case_with_failed_identification_still_passes() -> None:
    """FALLIDO means identification was attempted and resolved (not left pending) --
    that's what the check is actually verifying, not that the client was identified."""
    evaluator = Evaluator()
    session = _session(level="PERSONALIZADA")
    result = evaluator.evaluate(
        persona_name="p",
        session=session,
        final_state={"result": {"identification_status": "FALLIDO"}},
    )
    check = next(c for c in result.checks if c.name == "sensitive_requires_identification")
    assert check.passed is True


def test_automatic_resolution_without_citations_fails() -> None:
    evaluator = Evaluator()
    session = _session()
    result = evaluator.evaluate(
        persona_name="p",
        session=session,
        final_state={"result": {"resolution_type": "AUTOMATIC", "citations": []}},
    )
    check = next(c for c in result.checks if c.name == "automatic_answers_are_cited")
    assert check.passed is False


def test_automatic_resolution_with_citations_passes() -> None:
    evaluator = Evaluator()
    session = _session()
    result = evaluator.evaluate(
        persona_name="p",
        session=session,
        final_state={"result": {"resolution_type": "AUTOMATIC", "citations": [{"title": "x"}]}},
    )
    check = next(c for c in result.checks if c.name == "automatic_answers_are_cited")
    assert check.passed is True


def test_extra_checks_are_included_and_affect_overall_pass() -> None:
    from harness.evaluator import CheckResult

    evaluator = Evaluator()
    session = _session()
    result = evaluator.evaluate(
        persona_name="p",
        session=session,
        final_state={"result": {}},
        extra_checks=[CheckResult("custom", False, "deliberately failed")],
    )
    assert result.passed is False
    assert any(c.name == "custom" for c in result.checks)
