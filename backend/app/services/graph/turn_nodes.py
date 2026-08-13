"""Nodes for `turn_graph`, the port of `OrchestratorService.analyze_turn`.

Every node here is a faithful, line-by-line port of the original method
(`app/services/orchestrator.py`, pre-graph version) -- no behavior was changed, only the
control flow was made declarative. `PrioritizationAgent.run` stays a direct call inside
`persist_requirement` rather than its own node: it is a pure, synchronous, non-branching
scoring function, so promoting it to a node would only add indirection.
"""

from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command

from app.core.errors import AppError
from app.db.models import Requirement
from app.domain.enums import Category, ConsultationLevel, SessionStatus
from app.services.graph.state import GraphContext, OrchestrationState


async def guard_turn(state: OrchestrationState, runtime: Runtime[GraphContext]) -> Command:
    """Idempotency and state-machine guards, ported verbatim from `analyze_turn`
    (lines 72-105 of the pre-graph orchestrator). Ordering matters: a stale-retry
    short-circuit is checked before the `TURN_ALREADY_COMPLETED` error, which is
    checked before the state/clarification-flag guards."""
    db = runtime.context.db
    repository = runtime.context.repository
    kiosk_session = state["kiosk_session"]
    payload = state["turn_payload"]

    existing = await repository.requirement_by_turn(db, kiosk_session.id, payload.turn_id)
    if kiosk_session.status == SessionStatus.AWAITING_CONFIRMATION or (
        kiosk_session.status == SessionStatus.NEEDS_CLARIFICATION and existing
    ):
        pending = await repository.latest_requirement(db, kiosk_session.id)
        if pending:
            return Command(goto=END, update={"requirement": pending})
    if existing:
        raise AppError(
            "TURN_ALREADY_COMPLETED",
            "Ese turno ya fue procesado y el flujo avanzó",
            409,
            {"status": kiosk_session.status.value},
        )

    allowed_statuses = {
        SessionStatus.CREATED,
        SessionStatus.LISTENING,
        SessionStatus.NEEDS_CLARIFICATION,
    }
    if kiosk_session.status not in allowed_statuses:
        raise AppError(
            "INVALID_SESSION_STATE",
            "La sesión no admite un nuevo turno en su estado actual",
            409,
            {"status": kiosk_session.status.value},
        )
    if payload.is_clarification != (kiosk_session.status == SessionStatus.NEEDS_CLARIFICATION):
        raise AppError(
            "INVALID_CLARIFICATION",
            "El indicador de aclaracion no coincide con el estado de la sesion",
            409,
        )

    return Command(goto="mask_pii")


async def mask_pii(state: OrchestrationState, runtime: Runtime[GraphContext]) -> dict:
    kiosk_session = state["kiosk_session"]
    payload = state["turn_payload"]
    masked = runtime.context.pii.mask(payload.transcript)
    context = masked.masked_text
    if payload.is_clarification:
        previous = await runtime.context.repository.latest_requirement(
            runtime.context.db, kiosk_session.id
        )
        if previous:
            context = f"{previous.masked_text}\nAclaracion: {masked.masked_text}"
            previous.active = False
    return {
        "masked_context": context,
        "pii_metadata": {"types": masked.pii_types, "counts": masked.counts},
    }


async def classify(state: OrchestrationState, runtime: Runtime[GraphContext]) -> dict:
    decision, source = await runtime.context.classifier.run_with_source(state["masked_context"])
    return {"decision": decision, "classification_source": source}


def route_ambiguity(state: OrchestrationState, runtime: Runtime[GraphContext]) -> str:
    decision = state["decision"]
    kiosk_session = state["kiosk_session"]
    settings = runtime.context.settings
    needs_clarification = (
        decision.ambiguous or decision.confidence < settings.classification_confidence_threshold
    )
    if needs_clarification and kiosk_session.clarification_count < settings.max_clarifications:
        return "clarify"
    if needs_clarification:
        return "force_human"
    return "accept"


async def clarify(state: OrchestrationState) -> dict:
    kiosk_session = state["kiosk_session"]
    kiosk_session.clarification_count += 1
    kiosk_session.status = SessionStatus.NEEDS_CLARIFICATION
    return {}


async def force_human(state: OrchestrationState) -> dict:
    kiosk_session = state["kiosk_session"]
    decision = state["decision"].model_copy(
        update={
            "summary": state["masked_context"][:500],
            "category": Category.CONSULTA_GENERAL,
            "consultation_level": ConsultationLevel.GENERAL,
            "ambiguous": False,
            "clarification_question": None,
            "confidence": max(state["decision"].confidence, 0.5),
        }
    )
    kiosk_session.status = SessionStatus.AWAITING_CONFIRMATION
    return {"decision": decision, "force_human": True}


async def accept(state: OrchestrationState) -> dict:
    state["kiosk_session"].status = SessionStatus.AWAITING_CONFIRMATION
    return {}


async def persist_requirement(state: OrchestrationState, runtime: Runtime[GraphContext]) -> dict:
    kiosk_session = state["kiosk_session"]
    payload = state["turn_payload"]
    decision = state["decision"]
    proposed_priority = runtime.context.prioritizer.run(
        decision.category,
        decision.summary,
        kiosk_session.preferential_attention,
        urgency_detected=decision.urgency_detected,
        security_incident=decision.security_incident,
        distress_detected=decision.distress_detected,
    )
    requirement = Requirement(
        session_id=kiosk_session.id,
        turn_id=payload.turn_id,
        masked_text=state["masked_context"],
        pii_metadata=state["pii_metadata"],
        summary=decision.summary,
        customer_summary=decision.customer_summary,
        category=decision.category,
        proposed_priority=proposed_priority,
        consultation_level=decision.consultation_level,
        confidence=decision.confidence,
        classification_source=state["classification_source"],
        ambiguous=kiosk_session.status == SessionStatus.NEEDS_CLARIFICATION,
        clarification_question=decision.clarification_question,
        force_human=state.get("force_human", False),
        urgency_detected=decision.urgency_detected,
        security_incident=decision.security_incident,
        distress_detected=decision.distress_detected,
    )
    runtime.context.db.add(requirement)
    await runtime.context.db.flush()
    return {"requirement": requirement}
