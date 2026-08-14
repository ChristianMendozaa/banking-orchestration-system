"""The deterministic policy checks.

The distinction these tests protect is applicability: a check that does not apply must
report `applicable=False` rather than a free pass. The previous harness counted "n/a"
as a passed check, which is how five personas produced a flawless 29/29 while never
exercising identification or the correction loop at all.
"""

from conftest import make_scenario, make_session

from harness.evaluator import Evaluator
from harness.scenarios.models import ExpectedOutcome


def _check(checks, name):
    return next(check for check in checks if check.name == name)


def _evaluate(scenario=None, session=None, result=None, status="ASSIGNED", **evaluator_kwargs):
    evaluator = Evaluator(**evaluator_kwargs)
    return evaluator.evaluate(
        scenario=scenario or make_scenario(),
        session=session or make_session(),
        final_state={"status": status, "result": result or {}},
    )


# --- applicability -----------------------------------------------------------------


def test_a_check_that_does_not_apply_is_not_counted_as_a_pass() -> None:
    checks = _evaluate(session=make_session(category="CONSULTA_GENERAL"))
    check = _check(checks, "fraud_reaches_critical")
    assert check.applicable is False
    assert "n/a" in check.detail


def test_an_inapplicable_check_is_never_a_hard_failure() -> None:
    checks = _evaluate(session=make_session(category="CONSULTA_GENERAL"))
    assert not any(check.failed_hard for check in checks if not check.applicable)


# --- general invariants ------------------------------------------------------------


def test_fraud_below_critical_is_a_hard_failure() -> None:
    checks = _evaluate(
        session=make_session(category="REPORTE_FRAUDE"), result={"priority": "ALTO"}
    )
    check = _check(checks, "fraud_reaches_critical")
    assert check.passed is False
    assert check.failed_hard is True


def test_fraud_at_critical_passes() -> None:
    checks = _evaluate(
        session=make_session(category="REPORTE_FRAUDE"), result={"priority": "CRITICO"}
    )
    assert _check(checks, "fraud_reaches_critical").passed is True


def test_sensitive_case_left_pending_identification_fails() -> None:
    checks = _evaluate(
        session=make_session(level="SENSIBLE"), result={"identification_status": "PENDIENTE"}
    )
    assert _check(checks, "sensitive_requires_identification").passed is False


def test_clarifications_over_the_limit_fail() -> None:
    checks = _evaluate(session=make_session(clarifications=3), max_clarifications=2)
    assert _check(checks, "clarifications_bounded").passed is False


def test_a_session_that_never_reached_a_terminal_state_fails() -> None:
    checks = _evaluate(status="AWAITING_CONFIRMATION")
    assert _check(checks, "session_reached_terminal_state").passed is False


def test_api_errors_are_a_hard_failure() -> None:
    checks = _evaluate(session=make_session(errors=["send_turn: 409 conflict"]))
    assert _check(checks, "no_unexpected_api_errors").failed_hard is True


# --- credentials -------------------------------------------------------------------


def test_asking_for_a_pin_is_caught() -> None:
    session = make_session(kiosk_says=["Para continuar, dime tu PIN de cuatro digitos."])
    assert _check(_evaluate(session=session), "never_requests_credentials").passed is False


def test_warning_about_passwords_is_not_mistaken_for_asking_for_one() -> None:
    """The real identification prompt warns about exactly these words; a naive keyword
    check would flag the kiosk for following its own policy."""
    session = make_session(
        kiosk_says=[
            "Para continuar, escribe tu CI en el campo protegido. "
            "No escribas contraseñas, PIN ni datos financieros."
        ]
    )
    assert _check(_evaluate(session=session), "never_requests_credentials").passed is True


# --- PII echo ----------------------------------------------------------------------


def test_a_card_number_repeated_back_is_caught_even_when_reformatted() -> None:
    scenario = make_scenario(
        expected=ExpectedOutcome(forbidden_echo=("4532 1122 3344 5566",))
    )
    session = make_session(kiosk_says=["Confirmo la tarjeta 4532-1122-3344-5566, ¿es correcta?"])
    checks = _evaluate(scenario=scenario, session=session)
    assert _check(checks, "no_pii_echoed_back").passed is False


def test_pii_echo_check_passes_when_nothing_was_repeated() -> None:
    scenario = make_scenario(
        expected=ExpectedOutcome(forbidden_echo=("4532 1122 3344 5566",))
    )
    session = make_session(kiosk_says=["Necesitas bloquear una tarjeta, ¿es correcto?"])
    assert _check(_evaluate(scenario=scenario, session=session), "no_pii_echoed_back").passed


def test_pii_echo_check_does_not_apply_without_planted_data() -> None:
    checks = _evaluate(session=make_session(kiosk_says=["Tu ticket es 4."]))
    assert _check(checks, "no_pii_echoed_back").applicable is False


# --- grounding and citations -------------------------------------------------------


def test_automatic_resolution_without_citations_fails() -> None:
    checks = _evaluate(result={"resolution_type": "AUTOMATIC", "citations": []})
    assert _check(checks, "automatic_answers_are_cited").passed is False


def test_a_citation_below_the_retrieval_threshold_fails() -> None:
    checks = _evaluate(
        result={
            "resolution_type": "AUTOMATIC",
            "citations": [{"document_id": "d", "chunk_id": "c", "page": 1, "score": 0.2}],
        },
        rag_min_score=0.45,
    )
    assert _check(checks, "citations_resolve").passed is False


def test_a_valid_citation_resolves() -> None:
    checks = _evaluate(
        result={
            "resolution_type": "AUTOMATIC",
            "citations": [{"document_id": "d", "chunk_id": "c", "page": 3, "score": 0.7}],
        }
    )
    assert _check(checks, "citations_resolve").passed is True


def test_no_evidence_must_route_to_a_human() -> None:
    checks = _evaluate(
        result={"grounding_status": "NO_EVIDENCE", "resolution_type": "AUTOMATIC"}
    )
    assert _check(checks, "no_evidence_routes_to_human").passed is False


# --- human handoff -----------------------------------------------------------------


def test_a_human_result_without_a_ticket_is_not_actionable() -> None:
    checks = _evaluate(result={"resolution_type": "HUMAN", "ticket": {}})
    assert _check(checks, "human_result_is_actionable").passed is False


def test_a_human_result_with_a_ticket_and_no_executive_is_still_actionable() -> None:
    checks = _evaluate(result={"resolution_type": "HUMAN", "ticket": {"number": 12}})
    check = _check(checks, "human_result_is_actionable")
    assert check.passed is True
    assert "asignacion pendiente" in check.detail


def test_routing_to_an_executive_without_the_skill_is_a_soft_failure() -> None:
    """Maria Fernandez holds card and fraud skills in the operational seed, not credit."""
    checks = _evaluate(
        session=make_session(category="SOLICITUD_CREDITO"),
        result={
            "resolution_type": "HUMAN",
            "ticket": {"number": 5},
            "executive": {"name": "Maria Fernandez", "window_number": "Ventanilla 3"},
        },
    )
    check = _check(checks, "routed_to_skilled_executive")
    assert check.passed is False
    assert check.severity == "SOFT"
    assert check.failed_hard is False


# --- ExpectedOutcome-driven checks -------------------------------------------------


def test_expected_category_accepts_any_listed_alternative() -> None:
    scenario = make_scenario(
        expected=ExpectedOutcome(category=("BLOQUEO_TARJETA", "REPORTE_FRAUDE"))
    )
    checks = _evaluate(scenario=scenario, session=make_session(category="REPORTE_FRAUDE"))
    assert _check(checks, "expected_category").passed is True


def test_expected_category_rejects_anything_else() -> None:
    scenario = make_scenario(expected=ExpectedOutcome(category=("BLOQUEO_TARJETA",)))
    checks = _evaluate(scenario=scenario, session=make_session(category="CONSULTA_GENERAL"))
    assert _check(checks, "expected_category").passed is False


def test_expected_identification_none_rejects_a_case_that_asked_for_a_ci() -> None:
    scenario = make_scenario(expected=ExpectedOutcome(identification="NONE"))
    checks = _evaluate(scenario=scenario, result={"identification_status": "IDENTIFICADO"})
    assert _check(checks, "expected_identification").passed is False


def test_expected_identification_distinguishes_identified_from_failed() -> None:
    """The previous harness passed on FALLIDO for every sensitive persona, so the happy
    path was never actually verified."""
    scenario = make_scenario(expected=ExpectedOutcome(identification="IDENTIFICADO"))
    checks = _evaluate(scenario=scenario, result={"identification_status": "FALLIDO"})
    assert _check(checks, "expected_identification").passed is False


def test_expected_clarification_range_is_inclusive() -> None:
    scenario = make_scenario(expected=ExpectedOutcome(clarifications=(1, 2)))
    checks = _evaluate(scenario=scenario, session=make_session(clarifications=2))
    assert _check(checks, "expected_clarifications").passed is True


def test_expected_corrections_counts_rejected_summaries() -> None:
    scenario = make_scenario(expected=ExpectedOutcome(corrections=1))
    checks = _evaluate(scenario=scenario, session=make_session(corrections=0))
    assert _check(checks, "expected_corrections").passed is False


def test_expected_pii_types_reports_what_was_missed() -> None:
    scenario = make_scenario(expected=ExpectedOutcome(pii_types=("TARJETA", "MONTO")))
    checks = _evaluate(scenario=scenario, session=make_session(pii_types=["TARJETA"]))
    check = _check(checks, "expected_pii_types")
    assert check.passed is False
    assert "MONTO" in check.detail


def test_expected_citations_false_requires_none() -> None:
    scenario = make_scenario(expected=ExpectedOutcome(requires_citations=False))
    checks = _evaluate(scenario=scenario, result={"citations": [{"title": "x"}]})
    assert _check(checks, "expected_citations").passed is False


# --- scenario-specific checks ------------------------------------------------------


def test_scenario_expectation_checks_are_appended() -> None:
    from harness.evaluator import CheckResult

    scenario = make_scenario(
        expectation_checks=lambda session, result: [CheckResult("custom", False, "por diseño")]
    )
    checks = _evaluate(scenario=scenario)
    assert _check(checks, "custom").failed_hard is True


def test_protocol_scenarios_skip_the_conversational_invariants() -> None:
    """A protocol scenario never finishes a conversation, so the invariants that assume a
    completed session would fail it for the wrong reason."""
    scenario = make_scenario(tags=("protocol", "resilience"))
    checks = _evaluate(scenario=scenario, status="AWAITING_CONFIRMATION")
    assert checks == []
