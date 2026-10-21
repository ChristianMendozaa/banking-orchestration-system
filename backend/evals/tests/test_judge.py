"""The judge's wiring, dossier and failure mode.

`Judge.assess()` is never called against a real model here -- that is the live run's job
and costs money. What is verified is that the dossier carries everything the judge needs
to grade against a rubric rather than vibes, and that a judge failure becomes a scored
FAIL instead of vanishing.
"""

import json
from unittest.mock import AsyncMock

import pytest
from conftest import make_scenario, make_session, make_verdict
from pydantic import ValidationError

from harness.evaluator import CheckResult
from harness.judge import (
    CLIPPED_MARKER,
    JUDGE_SYSTEM_MESSAGE,
    DimensionScore,
    Judge,
    JudgeVerdict,
    build_dossier,
)
from harness.scenarios.models import ExpectedOutcome
from harness.session import ExchangeRecord

FINAL_STATE = {
    "status": "ASSIGNED",
    "result": {
        "priority": "CRITICO",
        "resolution_type": "HUMAN",
        "identification_status": "IDENTIFICADO",
        "ticket": {"number": 7},
        "executive": {"name": "Carlos Mamani", "window_number": "Ventanilla 1"},
        "citations": [{"title": "Tarjetas", "page": 1, "score": 0.72}],
        "outcomes": [
            {
                "need_index": 0,
                "customer_summary": "Necesitas reportar un cargo que no reconoces.",
                "category": "REPORTE_FRAUDE",
                "priority": "CRITICO",
                "resolution_type": "HUMAN",
                "ticket": {"number": 7},
                "executive": {"name": "Carlos Mamani", "window_number": "Ventanilla 1"},
                "grounding_status": "NOT_APPLICABLE",
            },
            {
                "need_index": 1,
                "customer_summary": "Quieres saber el horario de atención.",
                "category": "CONSULTA_GENERAL",
                "priority": "BAJO",
                "resolution_type": "AUTOMATIC",
                "ticket": {"number": 8},
                "response": "La sucursal atiende desde las 08:30.",
                "grounding_status": "GROUNDED",
            },
        ],
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


def test_dossier_carries_every_multi_need_outcome_as_ground_truth() -> None:
    payload = json.loads(_dossier().split("\n\n", 1)[1])
    outcomes = payload["final_recorded_state"]["all_outcomes"]
    assert [outcome["ticket"]["number"] for outcome in outcomes] == [7, 8]
    assert outcomes[1]["answer"] == "La sucursal atiende desde las 08:30."


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


def _payload(session, final_state=FINAL_STATE) -> dict:
    dossier = build_dossier(
        scenario=make_scenario(), session=session, final_state=final_state, checks=[]
    )
    return json.loads(dossier.split("\n\n", 1)[1])


def test_dossier_separates_what_is_said_from_what_is_shown() -> None:
    """2026-10-20: the on-screen paragraph was graded as if it had been read aloud."""
    session = make_session()
    session.exchanges = [
        ExchangeRecord(
            index=0,
            tool="send_turn",
            customer_text="¿Qué horario tienen?",
            kiosk_speech="Atendemos de ocho y media a siete.",
            screen_text="La Sucursal Centro atiende de lunes a viernes de 08:30 a 19:00 ...",
            response={"speech_plan": {"intent": "ANSWER", "guidance": "Dilo tal cual."}},
        ),
        ExchangeRecord(
            index=1,
            tool="send_turn",
            customer_text="Quiero hablar con alguien",
            kiosk_speech="Voy a derivarte con un ejecutivo.",
            response={"speech_plan": {"intent": "HANDOFF", "guidance": "Explícale por qué."}},
        ),
    ]
    answer, handoff = _payload(session)["transcript"]
    assert answer["kiosk_said"] == "Atendemos de ocho y media a siete."
    assert answer["kiosk_screen"].startswith("La Sucursal Centro")
    assert "kiosk_voice_guidance" not in answer
    assert handoff["kiosk_voice_guidance"] == "Explícale por qué."


def test_dossier_keeps_a_full_answer_and_marks_any_clipping() -> None:
    """At 800 characters the judge saw answers cut mid-sentence and faulted the kiosk."""
    long_answer = "a" * 1200
    state = {"status": "RESOLVED_AUTOMATIC", "result": {"response": long_answer}}
    assert (
        _payload(make_session(), state)["final_recorded_state"]["final_answer_to_customer"]
        == long_answer
    )

    state["result"]["response"] = "a" * 2000
    clipped = _payload(make_session(), state)["final_recorded_state"]["final_answer_to_customer"]
    assert clipped.endswith(CLIPPED_MARKER)


def test_dossier_lists_every_outcome_of_the_session() -> None:
    session = make_session()
    session.outcomes = [
        {"requirement_id": "r1", "answer": "El horario es de 08:30 a 19:00."},
        {"requirement_id": "r2", "answer": "Trae tu carnet vigente."},
    ]
    outcomes = _payload(session)["final_recorded_state"]["session_outcomes"]
    assert [outcome["requirement_id"] for outcome in outcomes] == ["r1", "r2"]


def test_the_rubric_states_the_policies_the_judge_used_to_fault() -> None:
    for policy in ("campo protegido", "clarification budget", "Partial answers", "kiosk_screen"):
        assert policy in JUDGE_SYSTEM_MESSAGE


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


def test_a_dimension_reasoning_over_the_length_cap_is_clipped_not_rejected() -> None:
    """Regression: the first Claude judge run rejected whole verdicts over a
    `policy_compliance.reasoning` a few characters past the cap. Anthropic does not
    enforce the cap while decoding, so the tokens were already spent; rejecting only paid
    for a retry and risked scoring a correct kiosk 1/10."""
    dimension = DimensionScore(score=5, reasoning="x" * 400)
    assert len(dimension.reasoning) == 240
    assert dimension.reasoning.endswith("…")


def test_a_dimension_reasoning_at_the_cap_is_kept_whole() -> None:
    reasoning = "x" * 240
    assert DimensionScore(score=5, reasoning=reasoning).reasoning == reasoning


def test_an_over_long_verdict_from_the_model_still_parses() -> None:
    """The path the SDK takes: JSON from the model validated against `JudgeVerdict`."""
    payload = make_verdict().model_dump()
    payload["policy_compliance"]["reasoning"] = "It confirmed before the handoff. " * 10
    payload["failures"] = [f"failure {index}" for index in range(8)]
    verdict = JudgeVerdict.model_validate_json(json.dumps(payload))
    assert len(verdict.policy_compliance.reasoning) == 240
    assert verdict.failures == [f"failure {index}" for index in range(5)]


def test_a_too_short_dimension_reasoning_is_still_rejected() -> None:
    with pytest.raises(ValidationError):
        DimensionScore(score=5, reasoning="ok")


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


# --- the model call -----------------------------------------------------------


def _response(verdict=None, stop_reason="end_turn"):
    return type("R", (), {"parsed_output": verdict, "stop_reason": stop_reason})()


def _judge_returning(*responses) -> Judge:
    judge = Judge("claude-haiku-5-5")
    judge._client.messages.parse = AsyncMock(side_effect=list(responses))
    return judge


async def _assess(judge: Judge) -> JudgeVerdict:
    return await judge.assess(
        scenario=make_scenario(),
        session=make_session(),
        final_state=FINAL_STATE,
        checks=[],
    )


async def test_the_judge_requests_a_structured_verdict_at_high_effort() -> None:
    judge = _judge_returning(_response(make_verdict(9)))
    await _assess(judge)
    kwargs = judge._client.messages.parse.await_args.kwargs
    assert kwargs["model"] == "claude-haiku-5-5"
    assert kwargs["output_format"] is JudgeVerdict
    assert kwargs["output_config"] == {"effort": "high"}
    assert "Review this kiosk session" in kwargs["messages"][0]["content"]


async def test_the_judge_caches_its_constant_rubric() -> None:
    from harness.judge import JUDGE_SYSTEM_MESSAGE

    judge = _judge_returning(_response(make_verdict(9)))
    await _assess(judge)
    [system] = judge._client.messages.parse.await_args.kwargs["system"]
    assert system["text"] == JUDGE_SYSTEM_MESSAGE
    assert system["cache_control"] == {"type": "ephemeral"}


async def test_every_assessment_is_an_independent_request_on_one_shared_client() -> None:
    """Shared client: it owns an HTTP connection pool, and one per call would leak a pool
    per scenario across a 41-scenario run. Independent request: one scenario's verdict
    must not colour the next, so each call carries only the rubric and its own dossier."""
    judge = _judge_returning(_response(make_verdict(9)), _response(make_verdict(7)))
    client = judge._client
    await _assess(judge)
    await _assess(judge)
    assert judge._client is client
    for call in client.messages.parse.await_args_list:
        assert len(call.kwargs["messages"]) == 1


async def test_closing_the_judge_closes_its_client() -> None:
    judge = Judge("claude-haiku-5-5")
    judge._client = AsyncMock()
    await judge.close()
    judge._client.close.assert_awaited_once()


def test_the_judge_prompt_states_it_grades_the_kiosk_not_the_customer() -> None:
    from harness.judge import JUDGE_SYSTEM_MESSAGE

    assert "grading THE KIOSK" in JUDGE_SYSTEM_MESSAGE
    assert "GROUND TRUTH" in JUDGE_SYSTEM_MESSAGE


async def test_assess_returns_the_structured_verdict() -> None:
    verdict = make_verdict(9)
    result = await _assess(_judge_returning(_response(verdict)))
    assert result is verdict


async def test_assess_retries_once_then_records_the_failure() -> None:
    judge = _judge_returning(RuntimeError("upstream is down"), RuntimeError("upstream is down"))
    result = await _assess(judge)
    assert judge._client.messages.parse.await_count == 2
    assert result.verdict == "FAIL"
    assert "upstream is down" in result.reasoning


async def test_a_failed_first_attempt_is_recovered_by_the_retry() -> None:
    verdict = make_verdict(8)
    result = await _assess(_judge_returning(RuntimeError("overloaded"), _response(verdict)))
    assert result is verdict


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
async def test_a_refused_or_truncated_verdict_is_not_trusted(stop_reason: str) -> None:
    """Either stop reason can still leave a `parsed_output` from an earlier text block, or
    none at all; neither is a verdict the judge finished giving."""
    judge = _judge_returning(_response(make_verdict(9), stop_reason), _response(None, stop_reason))
    result = await _assess(judge)
    assert result.verdict == "FAIL"
    assert f"stop_reason={stop_reason}" in result.reasoning


async def test_a_response_without_a_parsed_verdict_is_not_trusted() -> None:
    result = await _assess(_judge_returning(_response(None), _response(None)))
    assert result.verdict == "FAIL"
    assert "judge returned no verdict" in result.reasoning
