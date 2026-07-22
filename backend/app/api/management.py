from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_roles
from app.core.datetime import ensure_aware
from app.db.models import CaseRecord, Executive, Ticket, User
from app.db.session import get_db
from app.domain.enums import Category, Priority, TicketStatus, UserRole
from app.domain.schemas import (
    ExecutiveWorkload,
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
    executive_id: UUID | None,
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
    if executive_id:
        result.append(Ticket.executive_id == executive_id)
    return result, start, end


def _query_with_relations():
    return select(Ticket).options(selectinload(Ticket.case), selectinload(Ticket.executive))


@router.get("/metrics", response_model=ManagementMetrics)
async def metrics(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    category: Category | None = None,
    priority: Priority | None = None,
    executive_id: UUID | None = None,
    _: User = Depends(require_roles(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> ManagementMetrics:
    filters, _, _ = _filters(date_from, date_to, category, priority, executive_id)
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
    executives = list((await db.scalars(select(Executive).order_by(Executive.display_name))).all())
    now = datetime.now(UTC)
    waits: list[float] = []
    attention_times: list[float] = []
    category_counts: Counter[str] = Counter()
    priority_counts: Counter[str] = Counter()
    hourly_counts: Counter[str] = Counter()
    workloads: dict[UUID, Counter[TicketStatus]] = defaultdict(Counter)
    for ticket in tickets:
        case_record = ticket.case
        category_counts[case_record.category.value] += 1
        priority_counts[case_record.priority.value] += 1
        hour = ensure_aware(ticket.created_at).astimezone(LA_PAZ).strftime("%H:00")
        hourly_counts[hour] += 1
        wait_stop = ensure_aware(ticket.started_at) if ticket.started_at else now
        waits.append(max(0, (wait_stop - ensure_aware(ticket.created_at)).total_seconds() / 60))
        if ticket.started_at:
            attention_stop = ensure_aware(ticket.closed_at) if ticket.closed_at else now
            attention_times.append(
                max(0, (attention_stop - ensure_aware(ticket.started_at)).total_seconds() / 60)
            )
        if ticket.executive_id:
            workloads[ticket.executive_id][ticket.status] += 1

    pending = sum(ticket.status == TicketStatus.PENDIENTE for ticket in tickets)
    in_attention = sum(ticket.status == TicketStatus.EN_ATENCION for ticket in tickets)
    closed = sum(ticket.status == TicketStatus.CERRADO for ticket in tickets)
    return ManagementMetrics(
        total_cases=len(tickets),
        active_cases=pending + in_attention,
        pending_cases=pending,
        in_attention_cases=in_attention,
        closed_cases=closed,
        average_wait_minutes=round(sum(waits) / len(waits), 2) if waits else 0,
        average_attention_minutes=(
            round(sum(attention_times) / len(attention_times), 2) if attention_times else 0
        ),
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
        executives=[
            ExecutiveWorkload(
                id=executive.id,
                name=executive.display_name,
                title=executive.title,
                status=executive.status,
                pending=workloads[executive.id][TicketStatus.PENDIENTE],
                in_attention=workloads[executive.id][TicketStatus.EN_ATENCION],
                closed=workloads[executive.id][TicketStatus.CERRADO],
            )
            for executive in executives
        ],
    )


@router.get("/cases", response_model=ManagementCasesResponse)
async def cases(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    category: Category | None = None,
    priority: Priority | None = None,
    executive_id: UUID | None = None,
    status: TicketStatus | None = None,
    q: str | None = Query(default=None, max_length=120),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_roles(UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> ManagementCasesResponse:
    filters, _, _ = _filters(date_from, date_to, category, priority, executive_id)
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
                executive=ticket.executive.display_name if ticket.executive else None,
                status=ticket.status,
                attention_time_min=attention,
                wait_time_min=wait,
                resolution_outcome=ticket.resolution_outcome,
                created_at=created,
            )
        )
    return ManagementCasesResponse(items=items, page=page, page_size=page_size, total=total)
