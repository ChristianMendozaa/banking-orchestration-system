"""Locking a ticket for a supervised override, and recording who did it.

Every manager mutation is an override of something the orchestrator decided, so
each one writes both an `OperationalAuditEvent` (who) and a `TraceEvent` (what the
case saw). `record_audit` writes them together so neither can be forgotten.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.db.models import (
    OperationalAuditEvent,
    Ticket,
    User,
)
from app.domain.enums import TicketStatus
from app.domain.schemas import (
    ManagementTicketMutation,
)


async def locked_ticket(db: AsyncSession, ticket_id: UUID) -> Ticket:
    statement = (
        select(Ticket)
        .where(Ticket.public_id == ticket_id)
        .options(selectinload(Ticket.case), selectinload(Ticket.executive))
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    ticket = await db.scalar(statement)
    if not ticket:
        raise AppError("TICKET_NOT_FOUND", "Ticket inexistente", 404)
    if ticket.automatic or ticket.status != TicketStatus.PENDIENTE:
        raise AppError(
            "TICKET_NOT_REASSIGNABLE",
            "Solo pueden modificarse tickets humanos pendientes",
            409,
        )
    return ticket


def mutation_result(ticket: Ticket) -> ManagementTicketMutation:
    return ManagementTicketMutation(
        id=ticket.public_id,
        number=str(ticket.number),
        executive_id=ticket.executive_id,
        priority=ticket.case.priority,
        status=ticket.status,
        version=ticket.version,
    )


def record_audit(
    db: AsyncSession,
    *,
    user: User,
    action: str,
    target_type: str,
    target_id: str,
    metadata: dict,
) -> None:
    db.add(
        OperationalAuditEvent(
            actor_user_id=user.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata_json=metadata,
        )
    )
