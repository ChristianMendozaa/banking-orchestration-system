"""Runs scenarios against a live backend and collects scored results.

Kiosk sessions are fully independent -- each has its own opaque token and its own row --
so scenarios run concurrently behind a semaphore. The ceiling is deliberately modest:
`POST /kiosk/sessions` is rate-limited to 30 requests per minute per client IP
(`app/main.py`), and every scenario also drives real classification, embedding and
retrieval calls on the backend side.

A scenario that crashes is a scored `FAIL` for that scenario with the error preserved in
its reasoning, never a reason to abort the run: losing 29 results because one agent hit a
transient API error would be the worst possible failure mode for a suite this expensive.
"""

import asyncio
import contextlib
import time
import traceback

import structlog

from harness.agent import build_customer_agent
from harness.cli_customer import build_cli_customer_backend
from harness.client import KioskClient
from harness.evaluator import CheckResult, Evaluator
from harness.judge import Judge, JudgeVerdict
from harness.mcp_kiosk_server import KioskMcpServerPool, serve_kiosk_pool
from harness.model_client import build_model_client, resolve_provider
from harness.scenarios import SCENARIOS
from harness.scenarios.models import Scenario
from harness.scoring import ScenarioResult
from harness.session import ConversationSession

logger = structlog.get_logger()

INITIAL_TASK = "Empieza a contarle al kiosco tu situacion."

# Wall-clock ceiling for one scenario: the customer agent's whole tool-calling loop plus
# the judge call. Neither the OpenAI client nor AutoGen bounds the total, so without this
# a single stalled request holds its semaphore slot forever and the run never finishes --
# an expensive way to learn that one call hung. A timeout is a scored failure like any
# other, so the other 40 scenarios still report.
SCENARIO_TIMEOUT_SECONDS = 300
JUDGE_TIMEOUT_SECONDS = 180


def _expected_summary(scenario: Scenario) -> str:
    expected = scenario.expected
    parts = []
    if expected.category:
        parts.append("/".join(expected.category))
    if expected.consultation_level:
        parts.append("/".join(expected.consultation_level))
    if expected.priority:
        parts.append("/".join(expected.priority))
    if expected.resolution_type:
        parts.append(expected.resolution_type)
    if expected.identification and expected.identification != "NONE":
        parts.append(f"CI:{expected.identification}")
    return " · ".join(parts) or "—"


def _actual_summary(session: ConversationSession, final_state: dict) -> str:
    result = final_state.get("result") or {}
    parts = [
        str(value)
        for value in (
            session.last_category,
            session.last_consultation_level,
            result.get("priority"),
            result.get("resolution_type"),
        )
        if value
    ]
    if result.get("identification_status"):
        parts.append(f"CI:{result['identification_status']}")
    return " · ".join(parts) or str(final_state.get("status", "—"))


async def _assess_with_retry(
    judge: Judge,
    *,
    scenario: Scenario,
    session: ConversationSession,
    final_state: dict,
    checks: list[CheckResult],
) -> JudgeVerdict:
    """One retry before giving up on the judge. Judge calls are a single long request to a
    model or a local CLI, and a single slow one is not evidence about the kiosk."""
    try:
        return await asyncio.wait_for(
            judge.assess(
                scenario=scenario, session=session, final_state=final_state, checks=checks
            ),
            JUDGE_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning("judge_timed_out_retrying", scenario=scenario.name)
    return await asyncio.wait_for(
        judge.assess(scenario=scenario, session=session, final_state=final_state, checks=checks),
        JUDGE_TIMEOUT_SECONDS,
    )


async def run_scenario(
    client: KioskClient,
    evaluator: Evaluator,
    judge: Judge | None,
    scenario: Scenario,
    *,
    model: str,
    mcp_pool: KioskMcpServerPool | None = None,
    repetition: int = 1,
) -> ScenarioResult:
    started = time.monotonic()
    result = ScenarioResult(
        scenario=scenario.name,
        group=scenario.group,
        tags=list(scenario.tags),
        description=scenario.description,
        final_status="NOT_STARTED",
        expected_summary=_expected_summary(scenario),
        actual_summary="—",
        repetition=repetition,
    )
    session: ConversationSession | None = None
    try:
        session = await ConversationSession.start(
            client, preferential_attention=scenario.preferential_attention
        )
        result.session_id = session.session_id
        logger.info("scenario_started", scenario=scenario.name, session_id=session.session_id)

        async def conversation() -> list[CheckResult]:
            """Returns the protocol script's own checks, or nothing for a conversational
            scenario, whose checks all come from the evaluator.

            The customer's model client is per-scenario -- its persona is too -- so it is
            closed here rather than leaking a connection pool per scenario.
            """
            if scenario.script:
                return await scenario.script(session)
            provider, underlying_model = resolve_provider(model)
            if provider is not None:
                # Same 3 tools, same session, same INITIAL_TASK -- just handed to a
                # local CLI over MCP instead of AutoGen's native OpenAI tool-calling.
                # `session` is mutated in place by the tool calls either way, so nothing
                # below this branch needs to know which path ran. Borrowed from the
                # shared pool rather than a fresh per-scenario server -- see
                # `mcp_kiosk_server.serve_kiosk_pool` for why a fresh server per
                # scenario doesn't work against these CLIs in practice.
                if mcp_pool is None:
                    raise RuntimeError(
                        f"model={model!r} needs a running kiosk MCP pool "
                        "(run_all should have started one)"
                    )
                backend = build_cli_customer_backend(provider, underlying_model)
                async with mcp_pool.acquire(session) as mcp_url:
                    await backend.run(
                        scenario=scenario,
                        session=session,
                        mcp_url=mcp_url,
                        initial_task=INITIAL_TASK,
                        timeout_seconds=SCENARIO_TIMEOUT_SECONDS,
                    )
                return []
            # The customer is role-play plus picking one of three tools against an
            # explicit next_action instruction -- it does not need deep reasoning, and a
            # customer that reasons less is also less likely to second-guess its way off
            # the persona's script. "none" is the lowest effort this model family accepts
            # -- confirmed against a live 400 response, which listed the valid set as
            # none/low/medium/high/xhigh and rejected "minimal" outright.
            model_client = build_model_client(model, reasoning_effort="none")
            agent = build_customer_agent(
                model_client=model_client, session=session, scenario=scenario
            )
            try:
                await agent.run(task=INITIAL_TASK)
            finally:
                await model_client.close()
            return []

        script_checks = await asyncio.wait_for(conversation(), SCENARIO_TIMEOUT_SECONDS)
        if scenario.script is None and not session.exchanges:
            # The simulated customer never said anything. That is a harness failure, not a
            # kiosk one -- in the 2026-08-18 run the codex-backed customer silently declined
            # to utter `prompt_injection`'s injection string, and the empty session was
            # scored 1/10 as if the kiosk had failed a security test it was never given.
            # Retry once, then say plainly what happened instead of blaming the kiosk.
            logger.warning("customer_produced_no_turns", scenario=scenario.name, attempt=1)
            script_checks = await asyncio.wait_for(conversation(), SCENARIO_TIMEOUT_SECONDS)
        final_state = await session.final_status()

        result.final_status = str(final_state.get("status", "UNKNOWN"))
        result.actual_summary = _actual_summary(session, final_state)
        result.exchanges = session.exchanges
        result.final_state = final_state
        result.session_snapshot = {
            "last_category": session.last_category,
            "last_consultation_level": session.last_consultation_level,
            "clarification_rounds": session.clarification_rounds,
            "correction_rounds": session.correction_rounds,
            "identification_attempts": session.identification_attempts,
            "pii_types": session.pii_types,
            "errors": session.errors,
        }
        result.checks = [
            *evaluator.evaluate(scenario=scenario, session=session, final_state=final_state),
            *script_checks,
        ]
        # A protocol scenario has no free-text kiosk speech -- its script's own checks are
        # the entire evidence, and the judge would have nothing to assess beyond restating
        # them. `ScenarioResult.raw_score` already falls back to the deterministic score
        # when `verdict` is None, so skipping there costs no information, only a judge call.
        # The gate is the speech itself rather than "is this scripted", because a scripted
        # scenario can still produce a real conversation worth judging: `prompt_injection`
        # is driven from a fixed string precisely so the customer model cannot decline to
        # send it, but what the kiosk says back is exactly what needs qualitative review.
        # `kiosk_speech` is None for an exchange whose API call failed (`session._call`'s
        # error path), and an errored turn carries no speech to judge. Reading `.startswith`
        # off it crashed the whole scenario -- `cambio_de_tema` scored 1/10 on 2026-08-19 for
        # a harness AttributeError, after the kiosk had correctly refused an out-of-state
        # confirmation with a 409. A harness that dies on the error path hides exactly the
        # behaviour that path exists to test.
        speech = [
            exchange
            for exchange in session.exchanges
            if exchange.kiosk_speech and not exchange.kiosk_speech.startswith("HTTP")
        ]
        if scenario.script is None and not session.exchanges:
            # Still nothing after the retry above. Skip the judge -- there is no transcript
            # to assess -- and let `result.error` mark the row as a harness failure.
            result.error = "the simulated customer produced no turns"
        elif judge and speech:
            result.verdict = await _assess_with_retry(
                judge,
                scenario=scenario,
                session=session,
                final_state=final_state,
                checks=result.checks,
            )
    except TimeoutError:
        # Recorded distinctly from a crash: the conversation and its checks may already be
        # populated, and "the judge never answered" is a different diagnosis from "the
        # kiosk broke".
        stage = "judge" if result.checks else "conversation"
        logger.warning("scenario_timed_out", scenario=scenario.name, stage=stage)
        result.error = f"timed out during the {stage} stage"
        if not result.checks:
            result.final_status = "TIMEOUT"
            if session:
                result.exchanges = session.exchanges
            result.verdict = JudgeVerdict.unavailable(result.error)
        # Otherwise the kiosk answered and only the judge did not: keep the real final
        # status and the deterministic checks, and leave `verdict` unset so `raw_score`
        # falls through to `_deterministic_score()`. Scoring an unreachable judge as 1/10
        # punishes the system under test for the harness's own timeout -- it cost
        # `respuestas_monosilabicas` a passing run on 2026-08-18 with every check passing.
        # `result.error` still forces a FAIL status, so nothing passes quietly.
    except Exception as exc:  # noqa: BLE001 - one scenario's crash must not end the run
        logger.warning(
            "scenario_failed",
            scenario=scenario.name,
            error=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc(limit=3),
        )
        result.error = f"{type(exc).__name__}: {exc}"
        result.final_status = result.final_status or "ERROR"
        if session:
            result.exchanges = session.exchanges
        if result.verdict is None:
            result.verdict = JudgeVerdict.unavailable(result.error)

    result.duration_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "scenario_finished",
        scenario=scenario.name,
        status=result.status,
        score=result.score,
        seconds=round(result.duration_ms / 1000, 1),
    )
    return result


async def run_all(
    *,
    base_url: str,
    model: str,
    judge_model: str | None,
    max_clarifications: int,
    rag_min_score: float = 0.45,
    scenarios: list[Scenario] | None = None,
    concurrency: int = 4,
    repeat: int = 1,
) -> list[ScenarioResult]:
    evaluator = Evaluator(max_clarifications=max_clarifications, rag_min_score=rag_min_score)
    judge = Judge(judge_model) if judge_model else None
    selected = scenarios if scenarios is not None else SCENARIOS
    concurrency = max(1, concurrency)
    semaphore = asyncio.Semaphore(concurrency)
    # Only the CLI-customer path (claude-code / codex) needs a kiosk MCP pool -- the
    # native OpenAI customer calls the same 3 methods directly, no MCP involved. One
    # pool, sized to `concurrency`, for the whole run: see
    # `mcp_kiosk_server.serve_kiosk_pool` for why it must be reused across scenarios
    # rather than rebuilt per scenario.
    customer_provider, _ = resolve_provider(model)
    pool_cm = serve_kiosk_pool(concurrency) if customer_provider is not None else None

    try:
        async with contextlib.AsyncExitStack() as stack:
            client = await stack.enter_async_context(KioskClient(base_url))
            mcp_pool = await stack.enter_async_context(pool_cm) if pool_cm else None

            async def guarded(scenario: Scenario, repetition: int) -> ScenarioResult:
                async with semaphore:
                    return await run_scenario(
                        client,
                        evaluator,
                        judge,
                        scenario,
                        model=model,
                        mcp_pool=mcp_pool,
                        repetition=repetition,
                    )

            tasks = [
                guarded(scenario, repetition)
                for repetition in range(1, repeat + 1)
                for scenario in selected
            ]
            results = await asyncio.gather(*tasks)
    finally:
        if judge:
            await judge.close()

    # Keep catalog order rather than completion order, so two runs of the same suite
    # produce diffable reports.
    order = {scenario.name: index for index, scenario in enumerate(selected)}
    return sorted(results, key=lambda item: (order.get(item.scenario, 0), item.repetition))
