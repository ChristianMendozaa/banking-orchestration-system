"""The judge's wiring, dossier and failure mode.

`Judge.assess()` is never called against a real model here -- that is the live run's job
and costs money. What is verified is that the dossier carries everything the judge needs
to grade against a rubric rather than vibes, and that a judge failure becomes a scored
FAIL instead of vanishing.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from conftest import make_scenario, make_session, make_verdict
from pydantic import ValidationError

from harness.evaluator import CheckResult
from harness.judge import DimensionScore, Judge, JudgeVerdict, build_dossier
from harness.scenarios.models import ExpectedOutcome

FINAL_STATE = {
    "status": "ASSIGNED",
    "result": {
        "priority": "CRITICO",
        "resolution_type": "HUMAN",
        "identification_status": "IDENTIFICADO",
        "ticket": {"number": 7},
        "executive": {"name": "Carlos Mamani", "window_number": "Ventanilla 1"},
        "citations": [{"title": "Tarjetas", "page": 1, "score": 0.72}],
    },
}


def _dossier(**scenario_overrides) -> str:
    scenario = make_scenario(**scenario_overrides)
    session = make_session(
        category="REPORTE_FRAUDE",
        level="SENSIBLE",
        kiosk_says=["¿Me confirmas que necesitas reportar un fraude?"],
        customer_says=["No reconozco un cargo en mi cuenta."],
    )
    return build_dossier(
        scenario=scenario,
        session=session,
        final_state=FINAL_STATE,
        checks=[CheckResult("fraud_reaches_critical", True, "priority=CRITICO")],
    )


# --- dossier ------------------------------------------------------------------------


def test_dossier_carries_the_scenario_rubric() -> None:
    dossier = _dossier(
        expected=ExpectedOutcome(
            category=("REPORTE_FRAUDE",),
            policy_notes="Fraud must reach CRITICO and a fraud specialist.",
        )
    )
    assert "Fraud must reach CRITICO and a fraud specialist." in dossier
    assert "REPORTE_FRAUDE" in dossier


def test_dossier_carries_both_sides_of_the_conversation() -> None:
    dossier = _dossier()
    assert "No reconozco un cargo en mi cuenta." in dossier
    assert "¿Me confirmas que necesitas reportar un fraude?" in dossier


def test_dossier_carries_the_final_state_as_ground_truth() -> None:
    dossier = _dossier()
    for expected in ("Carlos Mamani", "IDENTIFICADO", "CRITICO", "Ventanilla 1"):
        assert expected in dossier


def test_dossier_labels_check_outcomes_for_applicable_checks() -> None:
    scenario = make_scenario()
    dossier = build_dossier(
        scenario=scenario,
        session=make_session(),
        final_state=FINAL_STATE,
        checks=[
            CheckResult("a", True, "ok"),
            CheckResult("b", False, "nope"),
            CheckResult.skip("c", "no aplica"),
        ],
    )
    assert '"outcome": "PASSED"' in dossier
    assert '"outcome": "FAILED"' in dossier


def test_dossier_keeps_not_applicable_checks_visible_but_compact() -> None:
    """A not-applicable check must never vanish -- the judge would otherwise be free to
    invent an expectation the scenario never set -- but it costs only its name, not a
    full record with a severity and detail the judge cannot act on anyway."""
    dossier = build_dossier(
        scenario=make_scenario(),
        session=make_session(),
        final_state=FINAL_STATE,
        checks=[
            CheckResult("a", True, "ok"),
            CheckResult.skip("fraud_reaches_critical", "no es un reporte de fraude"),
        ],
    )
    payload = json.loads(dossier.split("\n\n", 1)[1])
    assert payload["checks_not_applicable"] == ["fraud_reaches_critical"]
    assert "no es un reporte de fraude" not in dossier
    names = [check["name"] for check in payload["deterministic_checks"]]
    assert "fraud_reaches_critical" not in names


def test_dossier_truncates_a_long_check_detail() -> None:
    long_detail = "x" * 500
    dossier = build_dossier(
        scenario=make_scenario(),
        session=make_session(),
        final_state=FINAL_STATE,
        checks=[CheckResult("a", False, long_detail)],
    )
    payload = json.loads(dossier.split("\n\n", 1)[1])
    assert len(payload["deterministic_checks"][0]["detail"]) <= 160


def test_dossier_omits_expectations_the_scenario_does_not_set() -> None:
    """An `ExpectedOutcome` field left as None means "this scenario does not constrain
    it", and the judge must not read an absent constraint as an expectation of None."""
    dossier = _dossier(expected=ExpectedOutcome(category=("REPORTE_FRAUDE",)))
    expected_block = json.loads(dossier.split("\n\n", 1)[1])["scenario"]["expected_outcome"]
    assert expected_block == {"category": ["REPORTE_FRAUDE"]}


# --- the verdict model --------------------------------------------------------------


def test_a_score_outside_one_to_ten_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DimensionScore(score=11, reasoning="A long enough reason to pass validation.")


def test_a_dimension_reasoning_over_the_length_cap_is_rejected() -> None:
    """The cap on visible judge output is enforced by the schema, not just requested in
    the prompt -- a model that ignores the 'one or two sentences' instruction must not be
    able to blow the output-token budget anyway."""
    with pytest.raises(ValidationError):
        DimensionScore(score=5, reasoning="x" * 241)


def test_the_verdict_requires_substantive_reasoning() -> None:
    """The reasoning field is the whole point of the judge -- a one-word "bad" is useless
    to anyone reading the dashboard, so the schema itself rejects it."""
    with pytest.raises(ValidationError):
        JudgeVerdict.model_validate({**make_verdict().model_dump(), "reasoning": "bad"})


def test_dimensions_exposes_every_scored_axis() -> None:
    assert set(make_verdict().dimensions) == {
        "understanding",
        "routing",
        "policy_compliance",
        "communication",
        "resolution_quality",
    }


def test_an_unavailable_judge_is_a_recorded_failure_not_a_silent_gap() -> None:
    verdict = JudgeVerdict.unavailable("RateLimitError: slow down")
    assert verdict.verdict == "FAIL"
    assert verdict.overall_score == 1
    assert "RateLimitError: slow down" in verdict.reasoning


# --- the agent ----------------------------------------------------------------------


def test_the_judge_agent_requests_structured_output() -> None:
    agent = Judge("gpt-5.4").build_agent()
    assert agent._output_content_type is JudgeVerdict


def test_every_assessment_gets_a_fresh_agent_on_one_shared_client() -> None:
    """Fresh agent: `AssistantAgent` accumulates conversation state, so one scenario's
    verdict must not colour the next. Shared client: it owns an HTTP connection pool, and
    one per call would leak a pool per scenario across a 41-scenario run."""
    judge = Judge("gpt-5.4")
    first, second = judge.build_agent(), judge.build_agent()
    assert first is not second
    assert first._model_client is second._model_client


async def test_closing_the_judge_closes_its_model_client() -> None:
    judge = Judge("gpt-5.4")
    judge._model_client = AsyncMock()
    await judge.close()
    judge._model_client.close.assert_awaited_once()


def test_the_judge_prompt_states_it_grades_the_kiosk_not_the_customer() -> None:
    from harness.judge import JUDGE_SYSTEM_MESSAGE

    assert "grading THE KIOSK" in JUDGE_SYSTEM_MESSAGE
    assert "GROUND TRUTH" in JUDGE_SYSTEM_MESSAGE


async def test_assess_returns_the_structured_verdict() -> None:
    verdict = make_verdict(9)
    run = AsyncMock(return_value=type("R", (), {"messages": [type("M", (), {"content": verdict})]}))
    with patch.object(Judge, "build_agent") as build:
        build.return_value.run = run
        result = await Judge("gpt-5.4").assess(
            scenario=make_scenario(),
            session=make_session(),
            final_state=FINAL_STATE,
            checks=[],
        )
    assert result is verdict


async def test_assess_retries_once_then_records_the_failure() -> None:
    with patch.object(Judge, "build_agent") as build:
        build.return_value.run = AsyncMock(side_effect=RuntimeError("upstream is down"))
        result = await Judge("gpt-5.4").assess(
            scenario=make_scenario(),
            session=make_session(),
            final_state=FINAL_STATE,
            checks=[],
        )
    assert build.call_count == 2
    assert result.verdict == "FAIL"
    assert "upstream is down" in result.reasoning


async def test_a_judge_that_returns_the_wrong_type_is_not_trusted() -> None:
    run = AsyncMock(
        return_value=type("R", (), {"messages": [type("M", (), {"content": "just a string"})]})
    )
    with patch.object(Judge, "build_agent") as build:
        build.return_value.run = run
        result = await Judge("gpt-5.4").assess(
            scenario=make_scenario(),
            session=make_session(),
            final_state=FINAL_STATE,
            checks=[],
        )
    assert result.verdict == "FAIL"
    assert "unexpected judge output type" in result.reasoning
