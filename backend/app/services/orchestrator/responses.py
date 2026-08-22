"""Shaping graph state into API responses.

Every function here is pure with respect to the flow: it reads rows that the graphs
already wrote and returns a `TurnAnalysisResponse` or a `FlowResult`. The graphs perform
the state transitions; response shaping stays plain Python, exactly as it was before the
graphs existed -- see `app.services.graph.builder`.

Wording comes from `app.services.orchestrator.speech`; nothing here writes a sentence.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import CaseRecord, KioskSession, Requirement
from app.db.repositories import CaseRepository
from app.domain.enums import Priority, ResolutionType, SessionStatus
from app.domain.schemas import (
    ExecutiveAssignment,
    FlowResult,
    KnowledgeCitation,
    TicketResult,
    TurnAnalysisResponse,
)
from app.services.orchestrator.speech import (
    CAPTURE_SPEECH_TEXT,
    DECLINE_SPEECH_TEXT,
    IDENTIFICATION_SPEECH_TEXT,
    answer_plan,
    capture_plan,
    clarify_plan,
    confirm_plan,
    decline_plan,
    handoff_plan,
    identification_plan,
    pending_assignment_plan,
)


def completed_analysis_response(
    kiosk_session: KioskSession, requirement: Requirement, result: FlowResult
) -> TurnAnalysisResponse:

    return TurnAnalysisResponse(
        requirement_id=requirement.id,
        status=kiosk_session.status,
        summary=requirement.summary,
        customer_summary=requirement.customer_summary,
        category=requirement.category,
        priority=requirement.proposed_priority,
        consultation_level=requirement.consultation_level,
        confidence=requirement.confidence,
        pii_types=requirement.pii_metadata.get("types", []),
        next_action="COMPLETE",
        speech_text=result.speech_text,
        speech_plan=result.speech_plan,
        result=result,
    )


def analysis_response(
    kiosk_session: KioskSession, requirement: Requirement
) -> TurnAnalysisResponse:

    if kiosk_session.status == SessionStatus.DECLINED:
        return TurnAnalysisResponse(
            requirement_id=requirement.id,
            status=SessionStatus.DECLINED,
            summary=requirement.summary,
            customer_summary=requirement.customer_summary,
            category=requirement.category,
            priority=requirement.proposed_priority,
            consultation_level=requirement.consultation_level,
            confidence=requirement.confidence,
            pii_types=requirement.pii_metadata.get("types", []),
            next_action="DECLINE",
            speech_text=DECLINE_SPEECH_TEXT,
            speech_plan=decline_plan(),
        )
    clarify = kiosk_session.status == SessionStatus.NEEDS_CLARIFICATION
    question = requirement.clarification_question if clarify else None
    customer_summary = requirement.customer_summary.strip()
    confirmation_clause = customer_summary.rstrip(".?!")
    if confirmation_clause:
        confirmation_clause = confirmation_clause[0].lower() + confirmation_clause[1:]
    speech = question or f"¿Me confirmas si {confirmation_clause}?"
    return TurnAnalysisResponse(
        requirement_id=requirement.id,
        status=(
            SessionStatus.NEEDS_CLARIFICATION if clarify else SessionStatus.AWAITING_CONFIRMATION
        ),
        summary=requirement.summary,
        customer_summary=requirement.customer_summary,
        category=requirement.category,
        priority=requirement.proposed_priority,
        consultation_level=requirement.consultation_level,
        confidence=requirement.confidence,
        clarification_question=question,
        pii_types=requirement.pii_metadata.get("types", []),
        next_action="CLARIFY" if clarify else "CONFIRM",
        speech_text=speech,
        speech_plan=(
            clarify_plan(question)
            if question
            else confirm_plan(requirement.customer_summary, speech)
        ),
    )


def capture_result(kiosk_session: KioskSession, requirement: Requirement) -> FlowResult:
    return FlowResult(
        session_id=kiosk_session.id,
        requirement_id=requirement.id,
        status=SessionStatus.LISTENING,
        next_action="CAPTURE",
        customer_summary=requirement.customer_summary,
        priority=requirement.proposed_priority,
        speech_text=CAPTURE_SPEECH_TEXT,
        speech_plan=capture_plan(),
    )


def identification_result(
    kiosk_session: KioskSession,
    case: CaseRecord,
    requirement: Requirement,
) -> FlowResult:
    return FlowResult(
        session_id=kiosk_session.id,
        requirement_id=case.requirement_id,
        status=SessionStatus.AWAITING_IDENTIFICATION,
        next_action="IDENTIFY",
        customer_summary=requirement.customer_summary,
        priority=requirement.proposed_priority,
        identification_status=case.identification_status,
        speech_text=IDENTIFICATION_SPEECH_TEXT,
        speech_plan=identification_plan(),
    )


async def build_result(
    db: AsyncSession,
    session_id: UUID,
    repository: CaseRepository,
    settings: Settings,
) -> FlowResult:

    ticket = await repository.result_ticket(db, session_id)
    if not ticket:
        raise AppError("RESULT_NOT_READY", "El resultado aun no esta disponible", 409)
    case = ticket.case
    requirement = await db.get(Requirement, case.requirement_id)
    if not requirement:
        raise AppError("REQUIREMENT_NOT_FOUND", "El requerimiento del caso no existe", 409)
    assignment = None
    if ticket.executive:
        assignment = ExecutiveAssignment(
            id=ticket.executive.id,
            name=ticket.executive.display_name,
            title=ticket.executive.title,
            window_number=ticket.executive.window_number,
        )
    urgent_case = requirement.proposed_priority in {Priority.ALTO, Priority.CRITICO}
    if case.session.resolution_type == ResolutionType.AUTOMATIC:
        speech, plan = answer_plan(case.session.final_response)
    elif assignment:
        speech, plan = handoff_plan(
            category=case.category,
            ticket_number=ticket.number,
            estimated_wait_minutes=ticket.estimated_wait_minutes,
            assignment=assignment,
            urgent_case=urgent_case,
        )
    else:
        speech, plan = pending_assignment_plan(ticket.number)

    return FlowResult(
        session_id=session_id,
        requirement_id=case.requirement_id,
        status=case.session.status,
        next_action="COMPLETE",
        customer_summary=requirement.customer_summary,
        priority=requirement.proposed_priority,
        identification_status=case.identification_status,
        resolution_type=case.session.resolution_type,
        ticket=TicketResult(
            id=ticket.public_id,
            number=ticket.number,
            status=ticket.status,
            estimated_wait_minutes=ticket.estimated_wait_minutes,
        ),
        executive=assignment,
        response=case.session.final_response,
        speech_text=speech,
        speech_plan=plan,
        tracking_information=(
            f"Conserva el ticket {ticket.number}. {settings.support_tracking_information.strip()}"
        ),
        grounding_status=case.session.grounding_status,
        citations=[
            KnowledgeCitation.model_validate(citation) for citation in case.session.citations_json
        ],
    )
