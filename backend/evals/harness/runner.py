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
import time
import traceback

import structlog

from harness.agent import build_customer_agent
from harness.client import KioskClient
from harness.evaluator import CheckResult, Evaluator
from harness.judge import Judge, JudgeVerdict
from harness.model_client import build_model_client
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


async def run_scenario(
    client: KioskClient,
    evaluator: Evaluator,
    judge: Judge | None,
    scenario: Scenario,
    *,
    model: str,
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
            model_client = build_model_client(model)
            agent = build_customer_agent(
                model_client=model_client, session=session, scenario=scenario
            )
            try:
                await agent.run(task=INITIAL_TASK)
            finally:
                await model_client.close()
            return []

        script_checks = await asyncio.wait_for(conversation(), SCENARIO_TIMEOUT_SECONDS)
        final_state = await session.final_status()

        result.final_status = str(final_state.get("status", "UNKNOWN"))
        result.actual_summary = _actual_summary(session, final_state)
        result.exchanges = session.exchanges
        result.checks = [
            *evaluator.evaluate(scenario=scenario, session=session, final_state=final_state),
            *script_checks,
        ]
        if judge:
            result.verdict = await asyncio.wait_for(
                judge.assess(
                    scenario=scenario,
                    session=session,
                    final_state=final_state,
                    checks=result.checks,
                ),
                JUDGE_TIMEOUT_SECONDS,
            )
    except TimeoutError:
        # Recorded distinctly from a crash: the conversation and its checks may already be
        # populated, and "the judge never answered" is a different diagnosis from "the
        # kiosk broke".
        stage = "judge" if result.checks else "conversation"
        logger.warning("scenario_timed_out", scenario=scenario.name, stage=stage)
        result.error = f"timed out during the {stage} stage"
        result.final_status = "TIMEOUT"
        if session:
            result.exchanges = session.exchanges
        result.verdict = JudgeVerdict.unavailable(result.error)
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
    semaphore = asyncio.Semaphore(max(1, concurrency))

    try:
        async with KioskClient(base_url) as client:

            async def guarded(scenario: Scenario, repetition: int) -> ScenarioResult:
                async with semaphore:
                    return await run_scenario(
                        client, evaluator, judge, scenario, model=model, repetition=repetition
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
