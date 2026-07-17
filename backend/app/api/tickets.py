from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_roles
from app.core.datetime import ensure_aware
from app.core.errors import AppError
from app.db.models import CaseRecord, Ticket, TraceEvent, User
from app.db.session import get_db
from app.domain.enums import CaseStatus, Priority, TicketStatus, UserRole
from app.domain.schemas import (
    TicketDetail,
    TicketListItem,
    TicketPage,
    TicketStatusUpdate,
    TraceEventOut,
)

router = APIRouter(tags=["Operacion ejecutiva"])


def ticket_item(ticket: Ticket) -> TicketListItem:
    now = datetime.now(UTC)
    assigned = ensure_aware(ticket.assigned_at) if ticket.assigned_at else None
    elapsed = max(
        0, int((now - (assigned or ensure_aware(ticket.created_at))).total_seconds() // 60)
    )
    started = ensure_aware(ticket.started_at) if ticket.started_at else None
    wait = max(
        0,
        int(((started or now) - ensure_aware(ticket.created_at)).total_seconds() // 60),
    )
    executive = ticket.executive
    case = ticket.case
    return TicketListItem(
        id=ticket.public_id,
        number=str(ticket.number),
        category=case.category,
        priority=case.priority,
        summary=case.summary,
        time_assigned=assigned,
        minutes_elapsed=elapsed,
        executive_name=executive.display_name if executive else None,
        executive_title=executive.title if executive else None,
        window_number=executive.window_number if executive else None,
        status=ticket.status,
        client_session_id=f"SES-****-{str(case.session_id)[-4:].upper()}",
        wait_time_min=wait,
        identification_status=case.identification_status,
        preferential_attention=case.preferential_attention,
        version=ticket.version,
    )


def _ticket_options():
    return (
        selectinload(Ticket.case).selectinload(CaseRecord.events),
        selectinload(Ticket.executive),
    )


@router.get("/executive/tickets", response_model=TicketPage)
async def executive_tickets(
    status: TicketStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_roles(UserRole.EXECUTIVE)),
    db: AsyncSession = Depends(get_db),
) -> TicketPage:
    if not user.executive_id:
        raise AppError("EXECUTIVE_PROFILE_MISSING", "El usuario no tiene perfil ejecutivo", 409)
    filters = [Ticket.executive_id == user.executive_id]
    if status:
        filters.append(Ticket.status == status)
    total = await db.scalar(select(func.count(Ticket.number)).where(*filters)) or 0
    tickets = list(
        (
            await db.scalars(
                select(Ticket)
                .where(*filters)
                .options(*_ticket_options())
                .order_by(
                    case(
                        (CaseRecord.priority == Priority.CRITICO, 0),
                        (CaseRecord.priority == Priority.ALTO, 1),
                        (CaseRecord.priority == Priority.MEDIO, 2),
                        else_=3,
                    ),
                    Ticket.created_at,
                )
                .join(Ticket.case)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .unique()
        .all()
    )
    return TicketPage(
        items=[ticket_item(ticket) for ticket in tickets],
        page=page,
        page_size=page_size,
        total=total,
    )


async def _authorized_ticket(db: AsyncSession, public_id: UUID, user: User) -> Ticket:
    ticket = await db.scalar(
        select(Ticket).where(Ticket.public_id == public_id).options(*_ticket_options())
    )
    if not ticket:
        raise AppError("TICKET_NOT_FOUND", "Ticket inexistente", 404)
    if user.role == UserRole.EXECUTIVE and ticket.executive_id != user.executive_id:
        raise AppError("FORBIDDEN", "El ticket pertenece a otro ejecutivo", 403)
    return ticket


@router.get("/tickets/{ticket_id}", response_model=TicketDetail)
async def ticket_detail(
    ticket_id: UUID,
    user: User = Depends(require_roles(UserRole.EXECUTIVE, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> TicketDetail:
    ticket = await _authorized_ticket(db, ticket_id, user)
    item = ticket_item(ticket)
    return TicketDetail(
        **item.model_dump(),
        consultation_level=ticket.case.consultation_level,
        events=[TraceEventOut.model_validate(event) for event in ticket.case.events],
    )


@router.patch("/tickets/{ticket_id}/status", response_model=TicketDetail)
async def update_ticket_status(
    ticket_id: UUID,
    payload: TicketStatusUpdate,
    user: User = Depends(require_roles(UserRole.EXECUTIVE)),
    db: AsyncSession = Depends(get_db),
) -> TicketDetail:
    ticket = await _authorized_ticket(db, ticket_id, user)
    if ticket.automatic:
        raise AppError("AUTOMATIC_TICKET", "Un ticket automatico no admite cambios", 409)
    if ticket.version != payload.expected_version:
        raise AppError("VERSION_CONFLICT", "El ticket fue actualizado por otro proceso", 409)
    allowed = {
        TicketStatus.PENDIENTE: {TicketStatus.EN_ATENCION},
        TicketStatus.EN_ATENCION: {TicketStatus.CERRADO},
        TicketStatus.CERRADO: set(),
    }
    if payload.status != ticket.status and payload.status not in allowed[ticket.status]:
        raise AppError("INVALID_STATUS_TRANSITION", "Cambio de estado no permitido", 409)
    now = datetime.now(UTC)
    if payload.status != ticket.status:
        ticket.status = payload.status
        ticket.version += 1
        if payload.status == TicketStatus.EN_ATENCION:
            ticket.started_at = now
        elif payload.status == TicketStatus.CERRADO:
            ticket.closed_at = now
            ticket.case.status = CaseStatus.CLOSED
        event = TraceEvent(
            case_id=ticket.case_id,
            event_type="TICKET_STATUS_UPDATED",
            description=f"Estado de ticket actualizado a {payload.status.value}",
        )
        db.add(event)
        await db.commit()
        await db.refresh(ticket)
        ticket = await _authorized_ticket(db, ticket_id, user)
    item = ticket_item(ticket)
    return TicketDetail(
        **item.model_dump(),
        consultation_level=ticket.case.consultation_level,
        events=[TraceEventOut.model_validate(event) for event in ticket.case.events],
    )
