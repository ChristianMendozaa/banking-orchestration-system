"""Shaping graph state into API responses.

Every function here is pure with respect to the flow: it reads rows that the graphs
already wrote and returns a `TurnAnalysisResponse` or a `FlowResult`. The graphs perform
the state transitions; response shaping stays plain Python, exactly as it was before the
graphs existed -- see `app.services.graph.builder`.

Wording comes from `app.services.orchestrator.speech`; nothing here writes a sentence.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import CaseRecord, KioskSession, Requirement, Ticket
from app.db.repositories import CaseRepository
from app.domain.enums import (
    ConfirmationKind,
    GroundingStatus,
    IntentStatus,
    Priority,
    ResolutionType,
    SessionStatus,
)
from app.domain.schemas import (
    ExecutiveAssignment,
    FlowOutcome,
    FlowResult,
    KnowledgeCitation,
    TicketResult,
    TurnAnalysisResponse,
)
from app.services.orchestrator.speech import (
    CAPTURE_SPEECH_TEXT,
    DECLINE_SPEECH_TEXT,
    HANDOFF_CONFIRMATION_TEXT,
    IDENTIFICATION_SPEECH_TEXT,
    answer_plan,
    capture_plan,
    clarify_plan,
    compose_outcomes_plan,
    confirm_plan,
    decline_plan,
    handoff_confirmation_plan,
    handoff_plan,
    identification_plan,
    pending_assignment_plan,
    with_privacy_notice,
)


def completed_analysis_response(
    kiosk_session: KioskSession, requirement: Requirement, result: FlowResult
) -> TurnAnalysisResponse:
    speech, plan = with_privacy_notice(
        result.speech_text,
        result.speech_plan,
        requirement.pii_metadata.get("types", []),
    )
    result = result.model_copy(update={"speech_text": speech, "speech_plan": plan})
    return TurnAnalysisResponse(
        requirement_id=requirement.id,
        status=kiosk_session.status,
        summary=requirement.summary,
        customer_summary=requirement.customer_summary,
        category=requirement.category,
        priority=requirement.proposed_priority,
        consultation_level=requirement.consultation_level,
        confidence=requirement.confidence,
        routing_category=requirement.routing_category,
        intent_status=requirement.intent_status,
        confirmation_kind=requirement.confirmation_kind,
        clarification_outcome=requirement.clarification_outcome,
        pii_types=requirement.pii_metadata.get("types", []),
        next_action="COMPLETE",
        speech_text=speech,
        speech_plan=plan,
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
            routing_category=requirement.routing_category,
            intent_status=requirement.intent_status,
            confirmation_kind=requirement.confirmation_kind,
            clarification_outcome=requirement.clarification_outcome,
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
    handoff_confirmation = requirement.confirmation_kind is ConfirmationKind.HUMAN_HANDOFF
    confirmation_text = (
        HANDOFF_CONFIRMATION_TEXT
        if handoff_confirmation
        else f"¿Me confirmas si {confirmation_clause}?"
    )
    speech = question or confirmation_text
    plan = (
        clarify_plan(question)
        if question
        else (
            handoff_confirmation_plan()
            if handoff_confirmation
            else confirm_plan(requirement.customer_summary, speech)
        )
    )
    speech, plan = with_privacy_notice(
        speech,
        plan,
        requirement.pii_metadata.get("types", []),
    )
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
        routing_category=requirement.routing_category,
        intent_status=requirement.intent_status,
        confirmation_kind=requirement.confirmation_kind,
        clarification_outcome=requirement.clarification_outcome,
        clarification_question=question,
        pii_types=requirement.pii_metadata.get("types", []),
        next_action="CLARIFY" if clarify else "CONFIRM",
        speech_text=speech,
        speech_plan=plan,
    )


def capture_result(kiosk_session: KioskSession, requirement: Requirement) -> FlowResult:
    return FlowResult(
        session_id=kiosk_session.id,
        requirement_id=requirement.id,
        status=SessionStatus.LISTENING,
        next_action="CAPTURE",
        customer_summary=requirement.customer_summary,
        priority=requirement.proposed_priority,
        intent_status=requirement.intent_status,
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
        intent_status=requirement.intent_status,
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

    primary_requirement = await db.scalar(
        select(Requirement)
        .where(Requirement.session_id == session_id, Requirement.need_index == 0)
        .order_by(Requirement.created_at.desc())
        .limit(1)
    )
    if not primary_requirement:
        raise AppError("RESULT_NOT_READY", "El resultado aun no esta disponible", 409)
    cases = list(
        (
            await db.scalars(
                select(CaseRecord)
                .join(Requirement, CaseRecord.requirement_id == Requirement.id)
                .where(
                    CaseRecord.session_id == session_id,
                    Requirement.turn_id == primary_requirement.turn_id,
                )
                .order_by(Requirement.need_index)
                .options(
                    selectinload(CaseRecord.session),
                    selectinload(CaseRecord.ticket).selectinload(Ticket.executive),
                )
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if not cases:
        raise AppError("RESULT_NOT_READY", "El resultado aun no esta disponible", 409)

    requirements = {
        requirement.id: requirement
        for requirement in await repository.requirements_for_turn(
            db, session_id, primary_requirement.turn_id
        )
    }
    outcomes: list[FlowOutcome] = []
    for case in cases:
        requirement = requirements[case.requirement_id]
        ticket = case.ticket
        assignment = None
        if ticket and ticket.executive:
            assignment = ExecutiveAssignment(
                id=ticket.executive.id,
                name=ticket.executive.display_name,
                title=ticket.executive.title,
                window_number=ticket.executive.window_number,
            )
        outcomes.append(
            FlowOutcome(
                requirement_id=requirement.id,
                need_index=requirement.need_index,
                customer_summary=requirement.customer_summary,
                category=case.category,
                priority=requirement.proposed_priority,
                identification_status=case.identification_status,
                resolution_type=case.resolution_type or ResolutionType.HUMAN,
                ticket=(
                    TicketResult(
                        id=ticket.public_id,
                        number=ticket.number,
                        status=ticket.status,
                        estimated_wait_minutes=ticket.estimated_wait_minutes,
                    )
                    if ticket
                    else None
                ),
                executive=assignment,
                response=case.final_response,
                grounding_status=case.grounding_status,
                grounding_detail=case.grounding_detail_json,
                citations=[
                    KnowledgeCitation.model_validate(citation) for citation in case.citations_json
                ],
            )
        )

    turn_count = await repository.turn_count(db, session_id)
    remaining_turns = max(0, settings.kiosk_max_turns - turn_count)
    has_human_outcome = any(outcome.resolution_type is ResolutionType.HUMAN for outcome in outcomes)
    conversation_can_continue = not has_human_outcome and remaining_turns > 0

    primary = outcomes[0]
    primary_case = cases[0]
    primary_ticket = primary_case.ticket
    primary_assignment = primary.executive
    urgent_case = primary.priority in {Priority.ALTO, Priority.CRITICO}
    if primary.resolution_type == ResolutionType.AUTOMATIC:
        speech, plan = answer_plan(
            primary.response, conversation_can_continue=conversation_can_continue
        )
    elif primary_assignment and primary_ticket:
        speech, plan = handoff_plan(
            category=primary_case.category,
            ticket_number=primary_ticket.number,
            estimated_wait_minutes=primary_ticket.estimated_wait_minutes,
            assignment=primary_assignment,
            urgent_case=urgent_case,
            unresolved_summary=(
                primary_requirement.handoff_summary
                if primary_requirement.intent_status is IntentStatus.UNRESOLVED
                else None
            ),
        )
    elif primary_ticket:
        speech, plan = pending_assignment_plan(primary_ticket.number)
    else:
        raise AppError("RESULT_NOT_READY", "La derivación todavía no tiene ticket", 409)

    speech, plan = compose_outcomes_plan(speech, plan, outcomes)

    grounding_outcomes = [
        outcome
        for outcome in outcomes
        if outcome.grounding_status is not GroundingStatus.NOT_APPLICABLE
    ]
    if not grounding_outcomes:
        aggregate_grounding_status = GroundingStatus.NOT_APPLICABLE
    elif any(
        outcome.grounding_status is GroundingStatus.NO_EVIDENCE for outcome in grounding_outcomes
    ):
        aggregate_grounding_status = GroundingStatus.NO_EVIDENCE
    else:
        aggregate_grounding_status = GroundingStatus.GROUNDED
    aggregate_citations = list(
        {
            citation.chunk_id: citation
            for outcome in grounding_outcomes
            for citation in outcome.citations
        }.values()
    )
    aggregate_grounding_detail = {
        "outcomes": [
            {
                "requirement_id": str(outcome.requirement_id),
                "need_index": outcome.need_index,
                "status": outcome.grounding_status.value,
                "detail": outcome.grounding_detail,
            }
            for outcome in grounding_outcomes
        ]
    }

    human_ticket_numbers = [
        outcome.ticket.number
        for outcome in outcomes
        if outcome.ticket is not None and outcome.resolution_type is ResolutionType.HUMAN
    ]
    display_outcome = next(
        (
            outcome
            for outcome in outcomes
            if outcome.resolution_type is ResolutionType.HUMAN and outcome.ticket is not None
        ),
        primary,
    )

    return FlowResult(
        session_id=session_id,
        requirement_id=primary.requirement_id,
        status=primary_case.session.status,
        next_action="COMPLETE",
        customer_summary=display_outcome.customer_summary,
        priority=display_outcome.priority,
        identification_status=display_outcome.identification_status,
        resolution_type=(ResolutionType.HUMAN if has_human_outcome else primary.resolution_type),
        ticket=display_outcome.ticket,
        executive=display_outcome.executive,
        response=primary.response,
        speech_text=speech,
        speech_plan=plan,
        tracking_information=(
            "Conserva "
            + ("los tickets " if len(human_ticket_numbers) > 1 else "el ticket ")
            + ", ".join(str(number) for number in human_ticket_numbers)
            + f". {settings.support_tracking_information.strip()}"
            if human_ticket_numbers
            else None
        ),
        grounding_status=aggregate_grounding_status,
        grounding_detail=aggregate_grounding_detail,
        intent_status=primary_requirement.intent_status,
        citations=aggregate_citations,
        outcomes=outcomes,
        conversation_can_continue=conversation_can_continue,
        remaining_turns=remaining_turns,
    )
