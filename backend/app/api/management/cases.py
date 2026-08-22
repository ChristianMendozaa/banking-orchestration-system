"""The case register: every case the orchestrator has classified, filterable."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.api.management.filters import build_filters, query_with_relations
from app.core.datetime import ensure_aware
from app.db.models import (
    CaseRecord,
    Ticket,
    User,
)
from app.db.session import get_db
from app.domain.enums import Category, Priority, TicketStatus, UserRole
from app.domain.schemas import (
    ManagementCasesResponse,
    ManagerialCase,
)

router = APIRouter()


@router.get("/cases", response_model=ManagementCasesResponse)
async def cases(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    category: Category | None = None,
    priority: Priority | None = None,
    executive_id: UUID | None = None,
    unassigned: bool | None = None,
    status: TicketStatus | None = None,
    q: str | None = Query(default=None, max_length=120),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_roles(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> ManagementCasesResponse:
    filters, _, _ = build_filters(date_from, date_to, category, priority, executive_id)
    if unassigned is True:
        filters.append(Ticket.executive_id.is_(None))
    elif unassigned is False:
        filters.append(Ticket.executive_id.is_not(None))
    if status:
        filters.append(Ticket.status == status)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        filters.append(
            or_(cast(Ticket.number, String).ilike(pattern), CaseRecord.summary.ilike(pattern))
        )
    total = (
        await db.scalar(select(func.count(Ticket.number)).join(Ticket.case).where(*filters)) or 0
    )
    tickets = list(
        (
            await db.scalars(
                query_with_relations()
                .join(Ticket.case)
                .where(*filters)
                .order_by(Ticket.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .unique()
        .all()
    )
    now = datetime.now(UTC)
    items = []
    for ticket in tickets:
        created = ensure_aware(ticket.created_at)
        started = ensure_aware(ticket.started_at) if ticket.started_at else None
        closed = ensure_aware(ticket.closed_at) if ticket.closed_at else None
        wait = max(0, int(((started or now) - created).total_seconds() // 60))
        attention = (
            max(0, int(((closed or now) - started).total_seconds() // 60)) if started else None
        )
        items.append(
            ManagerialCase(
                id=ticket.public_id,
                ticket=f"#{ticket.number}",
                summary=ticket.case.summary,
                category=ticket.case.category,
                priority=ticket.case.priority,
                executive_id=ticket.executive_id,
                executive=ticket.executive.display_name if ticket.executive else None,
                status=ticket.status,
                attention_time_min=attention,
                wait_time_min=wait,
                resolution_outcome=ticket.resolution_outcome,
                created_at=created,
                version=ticket.version,
            )
        )
    return ManagementCasesResponse(items=items, page=page, page_size=page_size, total=total)
