"""Nodes for `confirmation_graph`, the port of `OrchestratorService.confirm`.

The replay-healing section (`heal_decision` / `handle_replay`) is guard logic, not
documented policy, so -- per the same convention as `turn_nodes.guard_turn` -- it is
expressed with `Command`-returning nodes rather than static conditional edges. Every
original branch that returned `await self._finalize(...)` or `await self._build_result(...)`
routes to `next_action = "BUILD_RESULT"`; `OrchestratorService._dispatch_result` (the
adapter) resolves that marker into the actual response after `ainvoke()` returns.
"""

from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import CaseRecord, KioskSession, Requirement, TraceEvent
from app.domain.enums import CaseStatus, ConsultationLevel, IdentificationStatus, SessionStatus
from app.services.graph.state import GraphContext, OrchestrationState


async def create_case_for_requirement(
    db: AsyncSession, kiosk_session: KioskSession, requirement: Requirement
) -> CaseRecord:
    """Creates the `CaseRecord` for a confirmed (explicitly or implicitly) requirement,
    plus its `REQUIREMENT_CAPTURED` / `PII_MASKED` / `CASE_CLASSIFIED` trace events. Shared
    by the confirmation-graph acceptance path (`apply_confirmation`) and the turn-graph
    auto-resolve path (`auto_capture`) so a GENERAL request that skips confirmation still
    produces the exact same case shape as one that went through it."""
    identification_status = (
        IdentificationStatus.ANONIMO
        if requirement.consultation_level == ConsultationLevel.GENERAL
        else IdentificationStatus.PENDIENTE
    )
    case = CaseRecord(
        session_id=kiosk_session.id,
        requirement_id=requirement.id,
        category=requirement.category,
        consultation_level=requirement.consultation_level,
        identification_status=identification_status,
        summary=requirement.summary,
        preferential_attention=kiosk_session.preferential_attention,
        status=CaseStatus.CLASSIFIED,
        force_human=requirement.force_human,
    )
    db.add(case)
    await db.flush()
    db.add_all(
        [
            TraceEvent(
                case_id=case.id,
                event_type="REQUIREMENT_CAPTURED",
                description="Requerimiento capturado y confirmado",
            ),
            TraceEvent(
                case_id=case.id,
                event_type="PII_MASKED",
                description="Datos sensibles enmascarados antes del procesamiento interno",
                metadata_json={"pii_types": requirement.pii_metadata.get("types", [])},
            ),
            TraceEvent(
                case_id=case.id,
                event_type="CASE_CLASSIFIED",
                description=f"Caso clasificado como {case.category.value}",
                metadata_json={
                    "confidence": requirement.confidence,
                    "source": requirement.classification_source,
                },
            ),
        ]
    )
    return case


async def load_and_guard(state: OrchestrationState, runtime: Runtime[GraphContext]) -> dict:
    db = runtime.context.db
    kiosk_session = state["kiosk_session"]
    payload = state["confirmation_payload"]

    requirement = await db.scalar(
        select(Requirement).where(
            Requirement.id == payload.requirement_id,
            Requirement.session_id == kiosk_session.id,
        )
    )
    if not requirement:
        raise AppError(
            "REQUIREMENT_NOT_FOUND",
            "No encontramos el requerimiento que intentas confirmar",
            409,
        )
    # Superseded, not merely finished. This used to compare the requirement against the
    # session's newest *case*, which worked only while a session held one. Once a follow-up
    # question could open a second case, confirming a requirement that had no case yet --
    # every requirement, at the moment it is confirmed -- was measured against the case some
    # earlier question had left behind, and any customer who asked something answerable
    # before asking for something that needs confirming was told their answer belonged to a
    # previous request. Ask about opening hours, then ask for a loan, and the "sí" was
    # rejected with a 409.
    #
    # What the guard is actually for is a confirmation arriving for a request the customer
    # has already moved on from. That is a question about requirements, so it is asked of
    # requirements: this one is stale if a newer one has taken its place. A requirement that
    # is simply closed -- rejected, and not replaced -- is not stale, which is what keeps a
    # repeated rejection idempotent rather than a conflict.
    latest = await runtime.context.repository.latest_requirement(db, kiosk_session.id)
    if (
        latest is not None
        and latest.id != requirement.id
        and latest.created_at > requirement.created_at
    ):
        raise AppError(
            "REQUIREMENT_MISMATCH",
            "La confirmación corresponde a un requerimiento anterior",
            409,
        )
    case = await runtime.context.repository.case_by_requirement(
        db, requirement.id, with_ticket=True
    )
    return {"requirement": requirement, "case": case}


async def heal_decision(state: OrchestrationState) -> dict:
    requirement = state["requirement"]
    case = state.get("case")
    if requirement.confirmation_decision is None:
        if case:
            requirement.confirmation_decision = True
        elif not requirement.active and not requirement.ambiguous:
            requirement.confirmation_decision = False
    return {}


def route_replay(state: OrchestrationState) -> str:
    return "replay" if state["requirement"].confirmation_decision is not None else "fresh"


async def handle_replay(state: OrchestrationState) -> Command:
    requirement = state["requirement"]
    kiosk_session = state["kiosk_session"]
    case = state.get("case")
    payload = state["confirmation_payload"]

    if requirement.confirmation_decision != payload.confirmed:
        raise AppError(
            "CONFIRMATION_ALREADY_RECORDED",
            "La confirmación ya fue registrada con otra respuesta",
            409,
        )
    if not payload.confirmed:
        if kiosk_session.status != SessionStatus.LISTENING:
            raise AppError(
                "REQUIREMENT_MISMATCH",
                "La confirmación corresponde a un requerimiento anterior",
                409,
            )
        return Command(goto=END, update={"next_action": "CAPTURE"})
    if case and case.ticket:
        return Command(goto=END, update={"next_action": "BUILD_RESULT"})
    if case and case.identification_status == IdentificationStatus.PENDIENTE:
        kiosk_session.status = SessionStatus.AWAITING_IDENTIFICATION
        return Command(goto=END, update={"next_action": "IDENTIFY"})
    if case:
        return Command(goto="finalize")
    # Original fallthrough: confirmation_decision is set (healed or from a prior
    # request) but no case exists. In practice unreachable -- confirmation_decision
    # only ever becomes True alongside case creation in the same request -- kept for
    # exact fidelity with the pre-graph method rather than dropped as dead code.
    return Command(goto="validate_fresh_confirmation")  # pragma: no cover


async def validate_fresh_confirmation(
    state: OrchestrationState, runtime: Runtime[GraphContext]
) -> Command:
    kiosk_session = state["kiosk_session"]
    requirement = state["requirement"]

    if kiosk_session.status in {SessionStatus.RESOLVED_AUTOMATIC, SessionStatus.ASSIGNED}:
        return Command(goto=END, update={"next_action": "BUILD_RESULT"})
    if kiosk_session.status != SessionStatus.AWAITING_CONFIRMATION:
        raise AppError(
            "INVALID_SESSION_STATE",
            "La sesión no tiene un requerimiento pendiente de confirmación",
            409,
            {"status": kiosk_session.status.value},
        )
    pending = await runtime.context.repository.latest_requirement(
        runtime.context.db, kiosk_session.id
    )
    if not pending or pending.id != requirement.id:
        raise AppError(
            "REQUIREMENT_MISMATCH",
            "La confirmación corresponde a un requerimiento anterior",
            409,
        )
    if requirement.ambiguous:
        raise AppError(
            "CLARIFICATION_REQUIRED",
            "Primero responde la pregunta de aclaración",
            409,
        )
    return Command(goto="apply_confirmation")


async def apply_confirmation(state: OrchestrationState, runtime: Runtime[GraphContext]) -> Command:
    db = runtime.context.db
    kiosk_session = state["kiosk_session"]
    requirement = state["requirement"]
    payload = state["confirmation_payload"]
    case = state.get("case")

    requirement.confirmation_decision = payload.confirmed
    if not payload.confirmed:
        kiosk_session.correction_count += 1
        if kiosk_session.correction_count < runtime.context.settings.max_corrections:
            requirement.active = False
            kiosk_session.status = SessionStatus.LISTENING
            return Command(goto=END, update={"next_action": "CAPTURE"})
        # Out of corrections. Re-asking someone who has already rejected the summary this
        # many times is how a session ends in LISTENING with no ticket at all -- a person at
        # the counter can untangle in ten seconds what the kiosk has now failed to capture
        # twice. Keep the requirement as the record of what was understood and let
        # `finalize_nodes.eligibility_gate` route it straight to a human on `force_human`,
        # skipping RAG the same way a low-confidence guess does.
        requirement.force_human = True
        if case is None:
            case = await create_case_for_requirement(db, kiosk_session, requirement)
        else:
            case.force_human = True
        db.add(
            TraceEvent(
                case_id=case.id,
                event_type="CORRECTION_LIMIT_REACHED",
                description=(
                    "Se alcanzo el limite de correcciones; el caso se deriva a un ejecutivo"
                ),
                metadata_json={"corrections": kiosk_session.correction_count},
            )
        )
        return Command(goto="finalize", update={"case": case})

    if not case:
        case = await create_case_for_requirement(db, kiosk_session, requirement)

    if case.identification_status == IdentificationStatus.PENDIENTE:
        kiosk_session.status = SessionStatus.AWAITING_IDENTIFICATION
        return Command(goto=END, update={"case": case, "next_action": "IDENTIFY"})
    return Command(goto="finalize", update={"case": case})
