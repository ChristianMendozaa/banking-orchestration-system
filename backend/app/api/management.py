from collections import Counter
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_roles
from app.core.datetime import ensure_aware
from app.db.models import CaseRecord, Ticket, User
from app.db.session import get_db
from app.domain.enums import Category, Priority, TicketStatus, UserRole
from app.domain.schemas import (
    HourlyMetric,
    ManagementCasesResponse,
    ManagementMetrics,
    ManagerialCase,
    MetricSlice,
)

router = APIRouter(prefix="/management", tags=["Gestion gerencial"])
LA_PAZ = ZoneInfo("America/La_Paz")


def _default_period() -> tuple[datetime, datetime]:
    now = datetime.now(LA_PAZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def _filters(
    date_from: datetime | None,
    date_to: datetime | None,
    category: Category | None,
    priority: Priority | None,
):
    default_from, default_to = _default_period()
    if date_from and not date_from.tzinfo:
        date_from = date_from.replace(tzinfo=LA_PAZ)
    if date_to and not date_to.tzinfo:
        date_to = date_to.replace(tzinfo=LA_PAZ)
    start = date_from.astimezone(UTC) if date_from else default_from
    end = date_to.astimezone(UTC) if date_to else default_to
    result = [Ticket.created_at >= start, Ticket.created_at < end]
    if category:
        result.append(CaseRecord.category == category)
    if priority:
        result.append(CaseRecord.priority == priority)
    return result, start, end


def _query_with_relations():
    return select(Ticket).options(selectinload(Ticket.case), selectinload(Ticket.executive))


@router.get("/metrics", response_model=ManagementMetrics)
async def metrics(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    category: Category | None = None,
    priority: Priority | None = None,
    _: User = Depends(require_roles(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> ManagementMetrics:
    filters, _, _ = _filters(date_from, date_to, category, priority)
    tickets = list(
        (
            await db.scalars(
                _query_with_relations()
                .join(Ticket.case)
                .where(*filters)
                .order_by(Ticket.created_at)
            )
        )
        .unique()
        .all()
    )
    now = datetime.now(UTC)
    waits = []
    category_counts: Counter[str] = Counter()
    priority_counts: Counter[str] = Counter()
    hourly_counts: Counter[str] = Counter()
    for ticket in tickets:
        case = ticket.case
        category_counts[case.category.value] += 1
        priority_counts[case.priority.value] += 1
        hour = ensure_aware(ticket.created_at).astimezone(LA_PAZ).strftime("%H:00")
        hourly_counts[hour] += 1
        stop = ensure_aware(ticket.started_at) if ticket.started_at else now
        waits.append(max(0, (stop - ensure_aware(ticket.created_at)).total_seconds() / 60))
    return ManagementMetrics(
        total_cases=len(tickets),
        active_cases=sum(
            ticket.status in {TicketStatus.PENDIENTE, TicketStatus.EN_ATENCION}
            for ticket in tickets
        ),
        average_wait_minutes=round(sum(waits) / len(waits), 2) if waits else 0,
        critical_pending=sum(
            ticket.case.priority == Priority.CRITICO
            and ticket.status in {TicketStatus.PENDIENTE, TicketStatus.EN_ATENCION}
            for ticket in tickets
        ),
        by_category=[
            MetricSlice(name=name, value=value) for name, value in category_counts.items()
        ],
        by_priority=[
            MetricSlice(name=name, value=value) for name, value in priority_counts.items()
        ],
        hourly=[
            HourlyMetric(hour=hour, cases=value) for hour, value in sorted(hourly_counts.items())
        ],
    )


@router.get("/cases", response_model=ManagementCasesResponse)
async def cases(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    category: Category | None = None,
    priority: Priority | None = None,
    status: TicketStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_roles(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> ManagementCasesResponse:
    filters, _, _ = _filters(date_from, date_to, category, priority)
    if status:
        filters.append(Ticket.status == status)
    total = (
        await db.scalar(select(func.count(Ticket.number)).join(Ticket.case).where(*filters)) or 0
    )
    tickets = list(
        (
            await db.scalars(
                _query_with_relations()
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
    items = []
    for ticket in tickets:
        end = ticket.closed_at or ticket.started_at
        attention = (
            max(
                0,
                int((ensure_aware(end) - ensure_aware(ticket.created_at)).total_seconds() // 60),
            )
            if end
            else None
        )
        items.append(
            ManagerialCase(
                ticket=f"#{ticket.number}",
                category=ticket.case.category,
                priority=ticket.case.priority,
                executive=ticket.executive.display_name if ticket.executive else None,
                status=ticket.status,
                attention_time_min=attention,
                created_at=ensure_aware(ticket.created_at),
            )
        )
    return ManagementCasesResponse(items=items, page=page, page_size=page_size, total=total)
