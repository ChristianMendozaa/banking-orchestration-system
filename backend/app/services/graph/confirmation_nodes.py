"""Nodes for `confirmation_graph`, the port of `OrchestratorService.confirm`.

The replay-healing section (`heal_decision` / `handle_replay`) is guard logic, not
documented policy, so -- per the same convention as `turn_nodes.guard_turn` -- it is
expressed with `Command`-returning nodes rather than static conditional edges. Every
original branch that returned `await self._finalize(...)` or `await self._build_result(...)`
routes to `next_action = "BUILD_RESULT"`; `OrchestratorService._dispatch_result` (the
adapter) resolves that marker into the actual response after `ainvoke()` returns.
"""

import structlog
from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.metrics import STAGE_DURATION
from app.db.models import CaseRecord, KioskSession, Requirement, TraceEvent
from app.domain.enums import (
    CaseStatus,
    ConfirmationIntent,
    ConfirmationKind,
    ConsultationLevel,
    IdentificationStatus,
    IntentStatus,
    SessionStatus,
)
from app.domain.schemas import ConfirmationReading
from app.services.agents.rules.confirmation import unambiguous_confirmation
from app.services.agents.rules.language import unresolved_customer_summary
from app.services.graph.state import GraphContext, OrchestrationState

logger = structlog.get_logger()


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
        or requirement.intent_status is IntentStatus.UNRESOLVED
        else IdentificationStatus.PENDIENTE
    )
    case = CaseRecord(
        session_id=kiosk_session.id,
        requirement_id=requirement.id,
        category=requirement.routing_category,
        consultation_level=requirement.consultation_level,
        identification_status=identification_status,
        summary=requirement.handoff_summary or requirement.summary,
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
                description=(
                    "Derivacion humana confirmada con intencion aun no resuelta"
                    if requirement.intent_status is IntentStatus.UNRESOLVED
                    else "Requerimiento capturado y confirmado"
                ),
                metadata_json={
                    "intent_status": requirement.intent_status.value,
                    "confirmation_kind": requirement.confirmation_kind.value,
                    "routing_category": requirement.routing_category.value,
                },
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
    case = await runtime.context.repository.case_by_session(db, kiosk_session.id, with_ticket=True)
    if case and case.requirement_id != requirement.id:
        # A *finished* case for an earlier need is not this confirmation's case. `guard_turn`
        # deliberately lets a session carry a second, unrelated need once the first one has
        # been answered ("cases.session_id is no longer unique"), but a case is only created
        # at confirmation time -- so for that second need `case_by_session` hands back the
        # previous need's case and this guard used to reject the confirmation outright.
        #
        # The 2026-08-21 eval run caught it on `cambio_de_tema`: the branch-hours question
        # resolved automatically, the customer then reported a stolen card, and confirming it
        # returned REQUIREMENT_MISMATCH and stranded the session at AWAITING_CONFIRMATION with
        # nothing said back. An *unfinished* case for a different requirement is still a real
        # mismatch and still raises; a finalized one just means the session moved on.
        if case.ticket is None and case.resolution_type is None:
            raise AppError(
                "REQUIREMENT_MISMATCH",
                "La confirmación corresponde a un requerimiento anterior",
                409,
            )
        case = None
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

    # `confirmed` is a hint now and may be absent, so a retry of the same spoken turn must
    # not 409 simply because the client stopped asserting a boolean. The guard still fires
    # for a claim that genuinely contradicts what was recorded -- read from the words when
    # the cue tables can settle them, and never from a model on a replay.
    claimed = payload.confirmed
    if claimed is None and payload.transcript:
        claimed = unambiguous_confirmation(payload.transcript)
    if claimed is not None and requirement.confirmation_decision != claimed:
        raise AppError(
            "CONFIRMATION_ALREADY_RECORDED",
            "La confirmación ya fue registrada con otra respuesta",
            409,
        )
    if not requirement.confirmation_decision:
        if kiosk_session.status != SessionStatus.LISTENING:
            raise AppError(
                "REQUIREMENT_MISMATCH",
                "La confirmación corresponde a un requerimiento anterior",
                409,
            )
        return Command(goto=END, update={"next_action": "CAPTURE"})
    if case and (case.ticket or case.resolution_type is not None):
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


async def interpret_confirmation(state: OrchestrationState, runtime: Runtime[GraphContext]) -> dict:
    """Decide what the reply meant, here rather than in the browser.

    Cue matching settles the replies that cannot mean anything else, so a plain "sí" costs
    no round trip. Everything it cannot settle is read by the model against the summary the
    kiosk actually said -- which is the only way "sí, pero quiero consultar primero" stops
    being a yes, "claro, ¿qué entendiste?" stops being a yes, and "no, quería consultar los
    requisitos" keeps the request that should replace the one on the table.
    """
    payload = state["confirmation_payload"]
    requirement = state["requirement"]
    transcript = (payload.transcript or "").strip()

    if not transcript:
        # The text channel confirms with explicit buttons; there is nothing to read.
        intent = ConfirmationIntent.CONFIRM if payload.confirmed else ConfirmationIntent.REJECT
        return {"confirmation_reading": ConfirmationReading(intent=intent)}

    settled = unambiguous_confirmation(transcript)
    if settled is not None:
        intent = ConfirmationIntent.CONFIRM if settled else ConfirmationIntent.REJECT
        return {"confirmation_reading": ConfirmationReading(intent=intent)}

    provider = runtime.context.classifier.provider
    if provider is None:
        # No provider, and the cue tables abstained. Asking again is the only honest move:
        # guessing here spends a correction the person never made.
        return {"confirmation_reading": ConfirmationReading(intent=ConfirmationIntent.AMBIGUOUS)}
    try:
        with STAGE_DURATION.labels(stage="read_confirmation").time():
            reading = await provider.read_confirmation(
                requirement.customer_summary or requirement.summary, transcript
            )
    except Exception as exc:
        logger.warning("confirmation_reading_fallback", error_type=type(exc).__name__)
        return {"confirmation_reading": ConfirmationReading(intent=ConfirmationIntent.AMBIGUOUS)}
    return {"confirmation_reading": reading}


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
    unresolved_intent_confirmation = requirement.confirmation_kind is ConfirmationKind.HUMAN_HANDOFF
    if requirement.ambiguous and not unresolved_intent_confirmation:
        raise AppError(
            "CLARIFICATION_REQUIRED",
            "Primero responde la pregunta de aclaración",
            409,
        )
    return Command(goto="interpret_confirmation")


async def apply_confirmation(state: OrchestrationState, runtime: Runtime[GraphContext]) -> Command:
    db = runtime.context.db
    kiosk_session = state["kiosk_session"]
    requirement = state["requirement"]
    case = state.get("case")
    reading = state["confirmation_reading"]

    # Neither an answer nor a rejection. Nothing moves: the session stays where it is, the
    # correction budget is not spent on a correction that was never made, and the kiosk
    # answers or re-asks. Spending a correction here is how someone who asked what the kiosk
    # had understood ended up two rounds closer to being handed to a person.
    if reading.intent in {ConfirmationIntent.QUESTION, ConfirmationIntent.AMBIGUOUS}:
        return Command(
            goto=END,
            update={"next_action": "RECONFIRM", "confirmation_reading": reading},
        )

    confirmed = reading.intent is ConfirmationIntent.CONFIRM
    requirement.confirmation_decision = confirmed
    if not confirmed:
        kiosk_session.correction_count += 1
        if kiosk_session.correction_count < runtime.context.settings.max_corrections:
            requirement.active = False
            kiosk_session.status = SessionStatus.LISTENING
            # A correction that named what the person wanted instead carries it out of here
            # (`OrchestratorService.confirm` feeds it straight back through the turn
            # pipeline), so they are not asked to say the whole thing over again.
            return Command(
                goto=END,
                update={"next_action": "CAPTURE", "confirmation_reading": reading},
            )
        # Out of corrections. Re-asking someone who has already rejected the summary this
        # many times is how a session ends in LISTENING with no ticket at all -- a person at
        # the counter can untangle in ten seconds what the kiosk has now failed to capture
        # twice. Keep the requirement as the record of what was understood and let
        # `finalize_nodes.eligibility_gate` route it straight to a human on `force_human`,
        # skipping RAG the same way a low-confidence guess does.
        requirement.force_human = True
        requirement.intent_status = IntentStatus.UNRESOLVED
        requirement.confirmation_kind = ConfirmationKind.HUMAN_HANDOFF
        requirement.handoff_summary = unresolved_customer_summary(requirement.routing_category)
        requirement.customer_summary = requirement.handoff_summary
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

    if reading.added_need:
        # A yes that also raised something else -- "sí, y además no reconozco un cargo".
        # Recorded against the case rather than swallowed by the yes: this turn is already
        # committed to the request that was confirmed, and manufacturing a second case out
        # of one clause of a confirmation would be worse than naming it in the trail. The
        # trace event needs a case, which is why it is written here and not above.
        db.add(
            TraceEvent(
                case_id=case.id,
                event_type="ADDITIONAL_NEED_RAISED",
                description="La persona planteo otra necesidad al confirmar",
                metadata_json={"need": reading.added_need},
            )
        )

    if requirement.confirmation_kind is ConfirmationKind.HUMAN_HANDOFF:
        case.force_human = True
        return Command(goto="finalize", update={"case": case})

    if case.identification_status == IdentificationStatus.PENDIENTE:
        kiosk_session.status = SessionStatus.AWAITING_IDENTIFICATION
        return Command(goto=END, update={"case": case, "next_action": "IDENTIFY"})
    return Command(goto="finalize", update={"case": case})
