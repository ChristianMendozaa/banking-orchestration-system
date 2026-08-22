"""Query construction for the ticket endpoints.

The `selectinload` chains are shared rather than repeated because a ticket read that
forgets one of them turns into a lazy load on an async session, which raises rather
than degrading. `authorized_ticket` is the single ownership gate: an executive may
only reach their own tickets.
"""

from uuid import UUID

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.db.models import (
    CaseRecord,
    ClientReference,
    Identification,
    KioskSession,
    Ticket,
    User,
)
from app.domain.enums import (
    UserRole,
)


def _identity_option():
    return (
        selectinload(Ticket.case)
        .selectinload(CaseRecord.identification)
        .selectinload(Identification.client_reference)
    )


def ticket_list_options():
    return (selectinload(Ticket.case), _identity_option(), selectinload(Ticket.executive))


def ticket_detail_options():
    return (
        *ticket_list_options(),
        selectinload(Ticket.case).selectinload(CaseRecord.events),
        selectinload(Ticket.case)
        .selectinload(CaseRecord.session)
        .selectinload(KioskSession.conversation_messages),
    )


def search_filter(value: str):
    pattern = f"%{value.strip()}%"
    return or_(
        cast(Ticket.number, String).ilike(pattern),
        CaseRecord.summary.ilike(pattern),
        ClientReference.display_name.ilike(pattern),
        Identification.masked_identifier.ilike(pattern),
    )


async def authorized_ticket(
    db: AsyncSession,
    public_id: UUID,
    user: User,
    *,
    for_update: bool = False,
) -> Ticket:
    statement = (
        select(Ticket).where(Ticket.public_id == public_id).options(*ticket_detail_options())
    )
    if for_update and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    ticket = await db.scalar(statement)
    if not ticket:
        raise AppError("TICKET_NOT_FOUND", "Ticket inexistente", 404)
    if user.role == UserRole.EXECUTIVE and ticket.executive_id != user.executive_id:
        raise AppError("FORBIDDEN", "El ticket pertenece a otro ejecutivo", 403)
    return ticket
