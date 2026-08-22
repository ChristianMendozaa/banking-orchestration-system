"""Turning ticket rows into the executive-facing schemas.

`include_client_name` is the privacy switch: a manager sees the queue without the
customer's name, an executive holding the case sees it.
"""

from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.core.datetime import ensure_aware
from app.db.models import (
    Identification,
    Ticket,
    User,
)
from app.domain.enums import (
    UserRole,
)
from app.domain.schemas import (
    ConversationMessageOut,
    ProtectedIdentity,
    TicketDetail,
    TicketListItem,
    TraceEventOut,
)


def case_identification(ticket: Ticket) -> Identification | None:
    return ticket.case.identification


def ticket_item(ticket: Ticket, *, include_client_name: bool) -> TicketListItem:
    now = datetime.now(UTC)
    assigned = ensure_aware(ticket.assigned_at) if ticket.assigned_at else None
    elapsed = max(
        0, int((now - (assigned or ensure_aware(ticket.created_at))).total_seconds() // 60)
    )
    started = ensure_aware(ticket.started_at) if ticket.started_at else None
    wait = max(0, int(((started or now) - ensure_aware(ticket.created_at)).total_seconds() // 60))
    executive = ticket.executive
    case_record = ticket.case
    identification = case_identification(ticket)
    reference = identification.client_reference if identification else None
    return TicketListItem(
        id=ticket.public_id,
        number=str(ticket.number),
        category=case_record.category,
        priority=case_record.priority,
        summary=case_record.summary,
        time_assigned=assigned,
        minutes_elapsed=elapsed,
        executive_name=executive.display_name if executive else None,
        executive_title=executive.title if executive else None,
        window_number=executive.window_number if executive else None,
        status=ticket.status,
        client_session_id=f"SES-****-{str(case_record.session_id)[-4:].upper()}",
        wait_time_min=wait,
        estimated_wait_minutes=ticket.estimated_wait_minutes,
        identification_status=case_record.identification_status,
        preferential_attention=case_record.preferential_attention,
        client_display_name=(reference.display_name if include_client_name and reference else None),
        masked_identifier=identification.masked_identifier if identification else None,
        started_at=ticket.started_at,
        closed_at=ticket.closed_at,
        resolution_outcome=ticket.resolution_outcome,
        version=ticket.version,
    )


def ticket_detail_response(ticket: Ticket, user: User, settings: Settings) -> TicketDetail:
    identification = case_identification(ticket)
    reference = identification.client_reference if identification else None
    cutoff = datetime.now(UTC) - timedelta(days=settings.conversation_retention_days)
    messages = [
        ConversationMessageOut.model_validate(message)
        for message in ticket.case.session.conversation_messages
        if ensure_aware(message.created_at) >= cutoff
    ]
    is_executive = user.role == UserRole.EXECUTIVE
    item = ticket_item(ticket, include_client_name=is_executive)
    return TicketDetail(
        **item.model_dump(),
        consultation_level=ticket.case.consultation_level,
        identity=ProtectedIdentity(
            status=ticket.case.identification_status,
            display_name=reference.display_name if is_executive and reference else None,
            masked_identifier=identification.masked_identifier if identification else None,
            reveal_available=bool(
                is_executive
                and identification
                and identification.identifier_ciphertext
                and identification.identifier_nonce
                and identification.identifier_key_id
            ),
        ),
        conversation=messages,
        events=[TraceEventOut.model_validate(event) for event in ticket.case.events],
        resolution_note=ticket.resolution_note,
    )
