"""Runs every persona end-to-end against a live backend and collects EvalResults."""

import structlog

from harness.agent import build_customer_agent
from harness.client import KioskClient
from harness.evaluator import EvalResult, Evaluator
from harness.personas import PERSONAS, Persona
from harness.session import ConversationSession

logger = structlog.get_logger()

INITIAL_TASK = "Empieza a contarle al kiosco tu situacion."


async def run_persona(
    client: KioskClient, evaluator: Evaluator, persona: Persona, *, model: str
) -> EvalResult:
    session = await ConversationSession.start(
        client, preferential_attention=persona.preferential_attention
    )
    logger.info("persona_started", persona=persona.name, session_id=session.session_id)
    agent = build_customer_agent(model=model, session=session, persona=persona)

    try:
        task_result = await agent.run(task=INITIAL_TASK)
    except Exception as exc:
        # A persona whose agent crashes (API error, malformed tool call, etc.) is a
        # scored failure for that persona, not a reason to abort the whole eval run.
        logger.warning("persona_agent_failed", persona=persona.name, error=str(exc))
        return EvalResult(persona=persona.name, final_status="AGENT_ERROR")

    final_state = await session.final_status()
    extra_checks = persona.expectation_checks(session, final_state.get("result") or {})
    result = evaluator.evaluate(
        persona_name=persona.name,
        session=session,
        final_state=final_state,
        extra_checks=extra_checks,
    )
    logger.info(
        "persona_finished",
        persona=persona.name,
        passed=result.passed,
        stop_reason=task_result.stop_reason,
    )
    return result


async def run_all(
    *,
    base_url: str,
    model: str,
    max_clarifications: int,
    personas: list[Persona] | None = None,
) -> list[EvalResult]:
    evaluator = Evaluator(max_clarifications=max_clarifications)
    results = []
    async with KioskClient(base_url) as client:
        for persona in personas or PERSONAS:
            results.append(await run_persona(client, evaluator, persona, model=model))
    return results
