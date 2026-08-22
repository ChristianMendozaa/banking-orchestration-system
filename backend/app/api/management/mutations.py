"""Supervised overrides: executive availability, reassignment, priority raises.

Each one is audited -- see `audit.py` -- because each one overrides a decision the
orchestrator already made and a person has to own that.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_roles
from app.api.management.audit import locked_ticket, mutation_result, record_audit
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.models import (
    Executive,
    Ticket,
    TraceEvent,
    User,
)
from app.db.session import get_db
from app.domain.enums import CaseStatus, ExecutiveStatus, Priority, TicketStatus, UserRole
from app.domain.schemas import (
    ExecutiveStatusResult,
    ExecutiveStatusUpdate,
    ManagementTicketMutation,
    TicketAssignmentUpdate,
    TicketPriorityUpdate,
)

router = APIRouter()


@router.patch(
    "/executives/{executive_id}/status",
    response_model=ExecutiveStatusResult,
)
async def update_executive_status(
    executive_id: UUID,
    payload: ExecutiveStatusUpdate,
    user: User = Depends(require_roles(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> ExecutiveStatusResult:
    statement = select(Executive).where(Executive.id == executive_id)
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    executive = await db.scalar(statement)
    if not executive:
        raise AppError("EXECUTIVE_NOT_FOUND", "Ejecutivo inexistente", 404)
    if executive.version != payload.expected_version:
        raise AppError("VERSION_CONFLICT", "El ejecutivo fue actualizado por otro proceso", 409)
    if executive.status == payload.status:
        return ExecutiveStatusResult(
            id=executive.id,
            status=executive.status,
            version=executive.version,
        )

    previous_status = executive.status
    unassigned = 0
    if payload.status == ExecutiveStatus.INACTIVO:
        active = await db.scalar(
            select(Ticket).where(
                Ticket.executive_id == executive.id,
                Ticket.status == TicketStatus.EN_ATENCION,
            )
        )
        if active:
            raise AppError(
                "EXECUTIVE_HAS_ACTIVE_CASE",
                "No puede desactivarse un ejecutivo con una atención activa",
                409,
                {"ticket_id": str(active.public_id), "ticket_number": str(active.number)},
            )
        pending_statement = (
            select(Ticket)
            .where(
                Ticket.executive_id == executive.id,
                Ticket.status == TicketStatus.PENDIENTE,
            )
            .options(selectinload(Ticket.case))
        )
        if db.get_bind().dialect.name == "postgresql":
            pending_statement = pending_statement.with_for_update()
        pending = list((await db.scalars(pending_statement)).all())
        for ticket in pending:
            ticket.executive_id = None
            ticket.assigned_at = None
            ticket.estimated_wait_minutes = None
            ticket.version += 1
            ticket.case.status = CaseStatus.QUEUED
            db.add(
                TraceEvent(
                    case_id=ticket.case_id,
                    event_type="TICKET_UNASSIGNED",
                    description="Ticket devuelto a la cola por indisponibilidad del ejecutivo",
                    metadata_json={
                        "user_id": str(user.id),
                        "previous_executive_id": str(executive.id),
                    },
                )
            )
        unassigned = len(pending)

    executive.status = payload.status
    executive.version += 1
    record_audit(
        db,
        user=user,
        action="EXECUTIVE_STATUS_UPDATED",
        target_type="EXECUTIVE",
        target_id=str(executive.id),
        metadata={
            "previous_status": previous_status.value,
            "new_status": payload.status.value,
            "unassigned_tickets": unassigned,
        },
    )
    await db.commit()
    return ExecutiveStatusResult(
        id=executive.id,
        status=executive.status,
        version=executive.version,
        unassigned_tickets=unassigned,
    )


@router.patch(
    "/tickets/{ticket_id}/assignment",
    response_model=ManagementTicketMutation,
)
async def update_ticket_assignment(
    ticket_id: UUID,
    payload: TicketAssignmentUpdate,
    user: User = Depends(require_roles(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ManagementTicketMutation:
    ticket = await locked_ticket(db, ticket_id)
    if ticket.version != payload.expected_version:
        raise AppError("VERSION_CONFLICT", "El ticket fue actualizado por otro proceso", 409)
    previous_id = ticket.executive_id
    if previous_id == payload.executive_id:
        return mutation_result(ticket)

    executive = None
    if payload.executive_id:
        executive_statement = select(Executive).where(Executive.id == payload.executive_id)
        if db.get_bind().dialect.name == "postgresql":
            executive_statement = executive_statement.with_for_update()
        executive = await db.scalar(executive_statement)
        if not executive:
            raise AppError("EXECUTIVE_NOT_FOUND", "Ejecutivo inexistente", 404)
        if executive.status != ExecutiveStatus.DISPONIBLE:
            raise AppError(
                "EXECUTIVE_NOT_AVAILABLE",
                "El ejecutivo seleccionado no está disponible",
                409,
            )
        active_load = (
            await db.scalar(
                select(func.count(Ticket.number)).where(
                    Ticket.executive_id == executive.id,
                    Ticket.status.in_([TicketStatus.PENDIENTE, TicketStatus.EN_ATENCION]),
                )
            )
            or 0
        )
        ticket.assigned_at = datetime.now(UTC)
        ticket.estimated_wait_minutes = (active_load + 1) * settings.estimated_service_minutes
        executive.last_assigned_at = ticket.assigned_at
        ticket.case.status = CaseStatus.ASSIGNED
    else:
        ticket.assigned_at = None
        ticket.estimated_wait_minutes = None
        ticket.case.status = CaseStatus.QUEUED

    ticket.executive_id = payload.executive_id
    ticket.version += 1
    db.add(
        TraceEvent(
            case_id=ticket.case_id,
            event_type="TICKET_ASSIGNMENT_UPDATED",
            description=(
                f"Ticket asignado a {executive.display_name}"
                if executive
                else "Ticket devuelto a la cola sin asignar"
            ),
            metadata_json={
                "user_id": str(user.id),
                "previous_executive_id": str(previous_id) if previous_id else None,
                "new_executive_id": str(payload.executive_id) if payload.executive_id else None,
                "reason": payload.reason,
            },
        )
    )
    record_audit(
        db,
        user=user,
        action="TICKET_ASSIGNMENT_UPDATED",
        target_type="TICKET",
        target_id=str(ticket.public_id),
        metadata={
            "previous_executive_id": str(previous_id) if previous_id else None,
            "new_executive_id": str(payload.executive_id) if payload.executive_id else None,
            "reason": payload.reason,
        },
    )
    await db.commit()
    return mutation_result(ticket)


@router.patch(
    "/tickets/{ticket_id}/priority",
    response_model=ManagementTicketMutation,
)
async def raise_ticket_priority(
    ticket_id: UUID,
    payload: TicketPriorityUpdate,
    user: User = Depends(require_roles(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> ManagementTicketMutation:
    ticket = await locked_ticket(db, ticket_id)
    if ticket.version != payload.expected_version:
        raise AppError("VERSION_CONFLICT", "El ticket fue actualizado por otro proceso", 409)
    order = [Priority.BAJO, Priority.MEDIO, Priority.ALTO, Priority.CRITICO]
    previous = ticket.case.priority
    if order.index(payload.priority) <= order.index(previous):
        raise AppError(
            "PRIORITY_NOT_RAISED",
            "La prioridad manual solo puede elevarse",
            422,
        )
    ticket.case.priority = payload.priority
    ticket.version += 1
    db.add(
        TraceEvent(
            case_id=ticket.case_id,
            event_type="TICKET_PRIORITY_RAISED",
            description=f"Prioridad elevada de {previous.value} a {payload.priority.value}",
            metadata_json={
                "user_id": str(user.id),
                "previous_priority": previous.value,
                "new_priority": payload.priority.value,
                "reason": payload.reason,
            },
        )
    )
    record_audit(
        db,
        user=user,
        action="TICKET_PRIORITY_RAISED",
        target_type="TICKET",
        target_id=str(ticket.public_id),
        metadata={
            "previous_priority": previous.value,
            "new_priority": payload.priority.value,
            "reason": payload.reason,
        },
    )
    await db.commit()
    return mutation_result(ticket)
