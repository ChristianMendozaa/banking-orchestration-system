"""Running a scenario end to end, with every network boundary mocked.

The property that matters most here is containment: one scenario blowing up must not take
the other 40 with it. A suite this expensive cannot afford to lose a whole run to one
transient API error.
"""

import asyncio
from unittest.mock import AsyncMock, patch

from conftest import make_scenario, make_verdict

from harness.client import SessionHandle
from harness.evaluator import CheckResult, Evaluator
from harness.runner import _actual_summary, _expected_summary, run_scenario
from harness.scenarios.models import ExpectedOutcome
from harness.session import ConversationSession

FINAL_STATE = {
    "status": "ASSIGNED",
    "result": {
        "priority": "CRITICO",
        "resolution_type": "HUMAN",
        "identification_status": "IDENTIFICADO",
        "ticket": {"number": 3},
    },
}


def _session(final_state: dict | None = None) -> ConversationSession:
    client = AsyncMock()
    client.get_status.return_value = final_state if final_state is not None else FINAL_STATE
    session = ConversationSession(client, SessionHandle("sid-1", "tok-1"))
    session.last_category = "REPORTE_FRAUDE"
    session.last_consultation_level = "SENSIBLE"
    return session


async def _run(scenario, *, session=None, judge=None, model="gpt-5.4-mini"):
    session = session or _session()
    with patch.object(ConversationSession, "start", AsyncMock(return_value=session)):
        return await run_scenario(AsyncMock(), Evaluator(), judge, scenario, model=model)


async def test_a_protocol_scenario_runs_its_script_and_keeps_its_checks() -> None:
    async def script(session):
        session.record_raw("send_identification", "CI antes de confirmar", 409, {"code": "X"})
        return [CheckResult("guard_held", True, "status=409")]

    result = await _run(make_scenario(tags=("protocol", "resilience"), script=script))
    assert [check.name for check in result.checks] == ["guard_held"]
    assert result.exchanges[0].customer_text == "CI antes de confirmar"


async def test_a_protocol_scenario_that_fails_its_guard_is_a_hard_failure() -> None:
    async def script(session):
        return [CheckResult("guard_held", False, "status=200, el guard no actuo")]

    result = await _run(make_scenario(tags=("protocol",), script=script))
    assert result.status == "FAIL"
    assert result.score <= 4


async def test_a_conversational_scenario_drives_the_customer_agent() -> None:
    scenario = make_scenario(expected=ExpectedOutcome(category=("REPORTE_FRAUDE",)))
    with patch("harness.runner.build_customer_agent") as build:
        build.return_value.run = AsyncMock()
        result = await _run(scenario)
    build.assert_called_once()
    client = build.call_args.kwargs["model_client"]
    assert client.model_info is not None  # the caller owns the client's lifecycle now
    assert result.final_status == "ASSIGNED"
    assert any(check.name == "expected_category" for check in result.checks)


async def test_a_conversational_scenario_on_a_cli_provider_uses_the_mcp_bridge() -> None:
    """`--model claude-code`/`codex` must route through the MCP bridge
    (`serve_kiosk_tools` + a CLI customer backend), never AutoGen's `build_customer_agent`
    -- the two paths are mutually exclusive per scenario."""
    scenario = make_scenario(expected=ExpectedOutcome(category=("REPORTE_FRAUDE",)))
    backend = AsyncMock()
    with (
        patch("harness.runner.build_customer_agent") as build_agent,
        patch("harness.runner.build_cli_customer_backend", return_value=backend) as build_backend,
        patch("harness.runner.serve_kiosk_tools") as serve,
    ):
        serve.return_value.__aenter__ = AsyncMock(return_value="http://127.0.0.1:1/mcp")
        serve.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await _run(scenario, model="claude-code")
    build_agent.assert_not_called()
    build_backend.assert_called_once_with("claude-code", None)
    backend.run.assert_awaited_once()
    assert backend.run.call_args.kwargs["mcp_url"] == "http://127.0.0.1:1/mcp"
    assert result.final_status == "ASSIGNED"


async def test_a_scripted_scenario_is_not_sent_to_the_judge() -> None:
    """A protocol scenario has no customer utterances and no free-text kiosk speech --
    its script's own checks are the entire evidence, so a judge call would only restate
    them at the price of a real one."""

    async def script(session):
        return [CheckResult("guard_held", True, "status=409")]

    judge = AsyncMock()
    result = await _run(make_scenario(tags=("protocol",), script=script), judge=judge)
    judge.assess.assert_not_awaited()
    assert result.verdict is None
    assert result.score == 10  # falls back to the deterministic score, not a judge score


async def test_a_conversational_scenario_is_still_sent_to_the_judge() -> None:
    judge = AsyncMock()
    judge.assess.return_value = make_verdict(8)
    with patch("harness.runner.build_customer_agent") as build:
        build.return_value.run = AsyncMock()
        result = await _run(make_scenario(), judge=judge)
    judge.assess.assert_awaited_once()
    assert result.verdict is not None


async def test_the_judge_sees_the_deterministic_checks() -> None:
    judge = AsyncMock()
    judge.assess.return_value = make_verdict(8)
    with patch("harness.runner.build_customer_agent") as build:
        build.return_value.run = AsyncMock()
        result = await _run(make_scenario(), judge=judge)
    assert judge.assess.await_args.kwargs["checks"] is result.checks
    assert result.verdict.overall_score == 8


async def test_a_crashing_scenario_becomes_a_scored_failure_not_an_exception() -> None:
    with patch("harness.runner.build_customer_agent") as build:
        build.return_value.run = AsyncMock(side_effect=ConnectionError("upstream refused"))
        result = await _run(make_scenario())
    assert result.status == "FAIL"
    assert "ConnectionError: upstream refused" in result.error
    assert "did not complete" in result.reasoning


async def test_a_crash_keeps_whatever_transcript_was_captured() -> None:
    session = _session()
    session.record_raw("send_turn", "Me robaron la tarjeta", 200, {"next_action": "CONFIRM"})
    with patch("harness.runner.build_customer_agent") as build:
        build.return_value.run = AsyncMock(side_effect=RuntimeError("boom"))
        result = await _run(make_scenario(), session=session)
    assert result.exchanges[0].customer_text == "Me robaron la tarjeta"


async def test_a_scenario_records_final_state_and_session_snapshot_for_rejudge() -> None:
    """`--rejudge` rebuilds a dossier from a stored report without a second live run --
    it needs the raw final state and these session scalars, not just the compact
    'expected -> actual' summary strings."""
    scenario = make_scenario(expected=ExpectedOutcome(category=("REPORTE_FRAUDE",)))
    with patch("harness.runner.build_customer_agent") as build:
        build.return_value.run = AsyncMock()
        result = await _run(scenario)
    assert result.final_state == FINAL_STATE
    assert result.session_snapshot["last_category"] == "REPORTE_FRAUDE"
    assert result.session_snapshot["last_consultation_level"] == "SENSIBLE"


async def test_a_scenario_records_how_long_it_took() -> None:
    async def script(session):
        return []

    result = await _run(make_scenario(tags=("protocol",), script=script))
    assert result.duration_ms >= 0


# --- summaries shown in the dashboard's "expected -> actual" column -----------------


def test_expected_summary_lists_only_what_the_scenario_constrains() -> None:
    scenario = make_scenario(
        expected=ExpectedOutcome(
            category=("REPORTE_FRAUDE",), priority=("CRITICO",), resolution_type="HUMAN"
        )
    )
    assert _expected_summary(scenario) == "REPORTE_FRAUDE · CRITICO · HUMAN"


def test_expected_summary_joins_alternatives_with_a_slash() -> None:
    scenario = make_scenario(
        expected=ExpectedOutcome(category=("BLOQUEO_TARJETA", "REPORTE_FRAUDE"))
    )
    assert _expected_summary(scenario) == "BLOQUEO_TARJETA/REPORTE_FRAUDE"


def test_an_unconstrained_scenario_shows_a_dash() -> None:
    assert _expected_summary(make_scenario()) == "—"


def test_actual_summary_reports_what_the_system_actually_did() -> None:
    summary = _actual_summary(_session(), FINAL_STATE)
    assert summary == "REPORTE_FRAUDE · SENSIBLE · CRITICO · HUMAN · CI:IDENTIFICADO"


def test_actual_summary_falls_back_to_the_session_status() -> None:
    session = ConversationSession(AsyncMock(), SessionHandle("sid", "tok"))
    assert _actual_summary(session, {"status": "FAILED"}) == "FAILED"


async def test_a_hung_conversation_times_out_instead_of_stalling_the_run() -> None:
    """Neither the OpenAI client nor AutoGen bounds a scenario's total wall clock, so one
    stalled request would otherwise hold its semaphore slot for the rest of the run."""
    import harness.runner as runner_module

    async def never_returns(*_args, **_kwargs):
        await asyncio.sleep(3600)

    with (
        patch.object(runner_module, "SCENARIO_TIMEOUT_SECONDS", 0.05),
        patch("harness.runner.build_customer_agent") as build,
    ):
        build.return_value.run = never_returns
        result = await _run(make_scenario())
    assert result.status == "FAIL"
    assert result.final_status == "TIMEOUT"
    assert "timed out during the conversation stage" in result.error


async def test_a_hung_judge_times_out_and_says_which_stage_failed() -> None:
    import harness.runner as runner_module

    judge = AsyncMock()

    async def never_returns(**_kwargs):
        await asyncio.sleep(3600)

    judge.assess = never_returns
    with (
        patch.object(runner_module, "JUDGE_TIMEOUT_SECONDS", 0.05),
        patch("harness.runner.build_customer_agent") as build,
    ):
        build.return_value.run = AsyncMock()
        result = await _run(make_scenario(), judge=judge)
    assert "timed out during the judge stage" in result.error
    assert result.checks, "the checks that already ran must survive a judge timeout"
