"""Nodes for the shared `finalize` subgraph, the port of `OrchestratorService._finalize`.

Compiled once and added as a node to both `confirmation_graph` and `identification_graph`
(see `builder.py`) -- the same subgraph instance, not a copy, mirroring how the pre-graph
code called the same `_finalize` method from both `confirm()` and `identify()`.

`_finalize`'s original last line was always `return await self._build_result(...)`, so
every terminal node here sets `next_action = "BUILD_RESULT"` rather than building a
response itself.
"""

from datetime import UTC, datetime
from uuid import uuid4

from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command

from app.core.errors import AppError
from app.db.models import Requirement, Ticket, TraceEvent
from app.domain.enums import (
    CaseStatus,
    ConsultationLevel,
    GroundingStatus,
    ResolutionType,
    SessionStatus,
    TicketStatus,
)
from app.services.graph.state import CLARIFICATION_JOINER, GraphContext, OrchestrationState


async def ticket_guard(state: OrchestrationState, runtime: Runtime[GraphContext]) -> Command:
    case = state["case"]
    existing = await runtime.context.repository.ticket_by_case(runtime.context.db, case.id)
    if existing:
        return Command(goto=END, update={"next_action": "BUILD_RESULT"})
    return Command(goto="assign_priority")


async def assign_priority(state: OrchestrationState, runtime: Runtime[GraphContext]) -> dict:
    db = runtime.context.db
    kiosk_session = state["kiosk_session"]
    case = state["case"]
    kiosk_session.status = SessionStatus.ORCHESTRATING
    case.status = CaseStatus.ORCHESTRATING
    requirement = await db.get(Requirement, case.requirement_id)
    if not requirement:
        raise AppError("REQUIREMENT_NOT_FOUND", "El requerimiento del caso no existe", 409)
    priority = requirement.proposed_priority
    case.priority = priority
    db.add(
        TraceEvent(
            case_id=case.id,
            event_type="PRIORITY_ASSIGNED",
            description=f"Prioridad asignada: {priority.value}",
        )
    )
    return {"requirement": requirement}


def eligibility_gate(state: OrchestrationState) -> str:
    return "route_human" if state["case"].force_human else "attempt_grounding"


async def attempt_grounding(state: OrchestrationState, runtime: Runtime[GraphContext]) -> dict:
    case = state["case"]
    requirement = state["requirement"]
    # The classifier's own single-need restatement is a sharper retrieval query than the raw
    # masked transcript -- across a clarification round masked_text is
    # "<vague opener>\nAclaracion: <real question>", which dilutes the embedding toward the
    # opener. summary is already masked (the classification prompt forbids it reconstructing
    # masked data), so it is safe to embed directly; fall back to masked_text if it is empty.
    grounding_query = requirement.summary.strip() or requirement.masked_text
    grounded_response = await runtime.context.initial_attention.run(
        runtime.context.db,
        case.id,
        case.category,
        case.consultation_level,
        grounding_query,
    )
    if grounded_response is None and CLARIFICATION_JOINER in requirement.masked_text:
        # The summary is written from `mask_pii`'s "<vague opener>\nAclaracion: <real
        # question>" context, so across a clarification round it can still carry enough of
        # the opener to pull the embedding away from what was actually asked --
        # `horarios_ambiguo` asked a clean question about branch hours on turn 2 and came
        # back NO_EVIDENCE while `horarios_directo`, the same question in one turn, grounds
        # with five citations. Retry once on the clarification alone before giving up and
        # sending a public-information question to a person.
        clarification = requirement.masked_text.rsplit(CLARIFICATION_JOINER, 1)[1].strip()
        if clarification and clarification != grounding_query:
            runtime.context.db.add(
                TraceEvent(
                    case_id=case.id,
                    event_type="RAG_RETRY_ON_CLARIFICATION",
                    description="Reintento de recuperacion usando solo la aclaracion",
                )
            )
            grounded_response = await runtime.context.initial_attention.run(
                runtime.context.db,
                case.id,
                case.category,
                case.consultation_level,
                clarification,
            )
    # InitialAttentionAgent.run bails out immediately (no knowledge lookup at all) for any
    # consultation level other than GENERAL, so grounding was only genuinely attempted -- as
    # opposed to simply not applicable to this case -- when the level is GENERAL.
    grounding_attempted = case.consultation_level == ConsultationLevel.GENERAL
    return {"grounded_response": grounded_response, "grounding_attempted": grounding_attempted}


def verify_grounding(state: OrchestrationState) -> str:
    return "automatic_ticket" if state.get("grounded_response") else "route_human"


async def automatic_ticket(state: OrchestrationState, runtime: Runtime[GraphContext]) -> dict:
    kiosk_session = state["kiosk_session"]
    case = state["case"]
    grounded_response = state["grounded_response"]
    now = datetime.now(UTC)
    ticket = Ticket(
        public_id=uuid4(),
        case_id=case.id,
        automatic=True,
        status=TicketStatus.CERRADO,
        assigned_at=now,
        estimated_wait_minutes=0,
        started_at=now,
        closed_at=now,
    )
    case.status = CaseStatus.RESOLVED
    kiosk_session.status = SessionStatus.RESOLVED_AUTOMATIC
    kiosk_session.resolution_type = ResolutionType.AUTOMATIC
    kiosk_session.final_response = grounded_response.answer
    kiosk_session.grounding_status = GroundingStatus.GROUNDED
    kiosk_session.citations_json = [
        citation.model_dump(mode="json") for citation in grounded_response.citations
    ]
    runtime.context.db.add(
        TraceEvent(
            case_id=case.id,
            event_type="AUTOMATIC_RESPONSE",
            description="Consulta general resuelta con evidencia documental",
            metadata_json={"citations": kiosk_session.citations_json},
        )
    )
    return {"ticket": ticket}


async def route_human(state: OrchestrationState, runtime: Runtime[GraphContext]) -> dict:
    db = runtime.context.db
    settings = runtime.context.settings
    kiosk_session = state["kiosk_session"]
    case = state["case"]
    now = datetime.now(UTC)

    grounding_attempted = state.get("grounding_attempted", False)
    kiosk_session.grounding_status = (
        GroundingStatus.NO_EVIDENCE if grounding_attempted else GroundingStatus.NOT_APPLICABLE
    )
    kiosk_session.citations_json = []
    if grounding_attempted:
        db.add(
            TraceEvent(
                case_id=case.id,
                event_type="RAG_NO_EVIDENCE",
                description=(
                    "Consulta general enrutada a un humano: no se encontro evidencia "
                    "suficiente en el corpus aprobado"
                ),
            )
        )
    routing = await runtime.context.derivation.run(db, case.category, case.summary)
    executive = routing.executive if routing else None
    estimated_wait = (
        (routing.active_load + 1) * settings.estimated_service_minutes if routing else None
    )
    ticket = Ticket(
        public_id=uuid4(),
        case_id=case.id,
        executive_id=executive.id if executive else None,
        automatic=False,
        status=TicketStatus.PENDIENTE,
        assigned_at=now if executive else None,
        estimated_wait_minutes=estimated_wait,
    )
    if executive:
        executive.last_assigned_at = now
        description = f"Caso derivado a {executive.display_name}"
    else:
        description = "Caso pendiente de asignacion por falta de ejecutivo disponible"
    case.status = CaseStatus.ASSIGNED if executive else CaseStatus.QUEUED
    kiosk_session.status = SessionStatus.ASSIGNED
    kiosk_session.resolution_type = ResolutionType.HUMAN
    db.add(
        TraceEvent(
            case_id=case.id,
            event_type="CASE_ROUTED",
            description=description,
            metadata_json=(
                {
                    "score": round(routing.score, 4),
                    "semantic_score": round(routing.semantic_score, 4),
                    "experience_score": round(routing.experience_score, 4),
                    "load_score": round(routing.load_score, 4),
                    "active_load": routing.active_load,
                    "estimated_wait_minutes": estimated_wait,
                }
                if routing
                else {"estimated_wait_minutes": None}
            ),
        )
    )
    return {"ticket": ticket}


async def persist_ticket(state: OrchestrationState, runtime: Runtime[GraphContext]) -> dict:
    runtime.context.db.add(state["ticket"])
    await runtime.context.db.flush()
    return {"next_action": "BUILD_RESULT"}
