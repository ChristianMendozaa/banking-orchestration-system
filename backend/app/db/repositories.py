from collections import defaultdict
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import CaseRecord, Executive, Requirement, Ticket
from app.domain.enums import ExecutiveStatus, TicketStatus


class CaseRepository:
    async def requirement_by_turn(
        self, db: AsyncSession, session_id: UUID, turn_id: UUID
    ) -> Requirement | None:
        return await db.scalar(
            select(Requirement).where(
                Requirement.session_id == session_id,
                Requirement.turn_id == turn_id,
            )
        )

    async def latest_requirement(self, db: AsyncSession, session_id: UUID) -> Requirement | None:
        return await db.scalar(
            select(Requirement)
            .where(Requirement.session_id == session_id, Requirement.active.is_(True))
            .order_by(Requirement.created_at.desc())
        )

    async def case_by_session(
        self,
        db: AsyncSession,
        session_id: UUID,
        *,
        with_identification: bool = False,
        with_ticket: bool = False,
    ) -> CaseRecord | None:
        query = select(CaseRecord).where(CaseRecord.session_id == session_id)
        options = []
        if with_identification:
            options.append(selectinload(CaseRecord.identification))
        if with_ticket:
            options.append(selectinload(CaseRecord.ticket))
        if options:
            query = query.options(*options)
        return await db.scalar(query)

    async def ticket_by_case(self, db: AsyncSession, case_id: UUID) -> Ticket | None:
        return await db.scalar(select(Ticket).where(Ticket.case_id == case_id))

    async def result_ticket(self, db: AsyncSession, session_id: UUID) -> Ticket | None:
        return await db.scalar(
            select(Ticket)
            .join(Ticket.case)
            .where(CaseRecord.session_id == session_id)
            .options(
                selectinload(Ticket.case).selectinload(CaseRecord.session),
                selectinload(Ticket.executive),
            )
            .execution_options(populate_existing=True)
        )


class ExecutiveRepository:
    async def available(self, db: AsyncSession) -> list[Executive]:
        return list(
            (
                await db.scalars(
                    select(Executive)
                    .where(Executive.status == ExecutiveStatus.DISPONIBLE)
                    .options(selectinload(Executive.skills))
                )
            ).all()
        )

    async def active_loads(self, db: AsyncSession) -> defaultdict[UUID, int]:
        rows = await db.execute(
            select(Ticket.executive_id, func.count(Ticket.number))
            .where(Ticket.status.in_([TicketStatus.PENDIENTE, TicketStatus.EN_ATENCION]))
            .group_by(Ticket.executive_id)
        )
        return defaultdict(int, {row[0]: row[1] for row in rows if row[0]})
