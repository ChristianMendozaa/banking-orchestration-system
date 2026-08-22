"""The manager dashboard: volumes, resolution mix, wait percentiles, workload."""

from collections import Counter, defaultdict
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.api.management.filters import (
    LA_PAZ,
    build_filters,
    percentile_of,
    query_with_relations,
)
from app.core.datetime import ensure_aware
from app.db.models import (
    Executive,
    Ticket,
    User,
)
from app.db.session import get_db
from app.domain.enums import Category, Priority, TicketStatus, UserRole
from app.domain.schemas import (
    ExecutiveWorkload,
    HourlyMetric,
    ManagementMetrics,
    MetricSlice,
)

router = APIRouter()


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
    filters, _, _ = build_filters(date_from, date_to, category, priority, executive_id)
    tickets = list(
        (
            await db.scalars(
                query_with_relations().join(Ticket.case).where(*filters).order_by(Ticket.created_at)
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
        if not ticket.automatic and ticket.started_at:
            waits.append(
                max(
                    0,
                    (
                        ensure_aware(ticket.started_at) - ensure_aware(ticket.created_at)
                    ).total_seconds()
                    / 60,
                )
            )
        if ticket.started_at and not ticket.automatic:
            attention_stop = ensure_aware(ticket.closed_at) if ticket.closed_at else now
            attention_times.append(
                max(0, (attention_stop - ensure_aware(ticket.started_at)).total_seconds() / 60)
            )
        if ticket.executive_id:
            workloads[ticket.executive_id][ticket.status] += 1

    pending = sum(ticket.status == TicketStatus.PENDIENTE for ticket in tickets)
    in_attention = sum(ticket.status == TicketStatus.EN_ATENCION for ticket in tickets)
    closed = sum(ticket.status == TicketStatus.CERRADO for ticket in tickets)
    automatic = sum(ticket.automatic for ticket in tickets)
    human = len(tickets) - automatic
    pending_ages = [
        max(
            0,
            int((now - ensure_aware(ticket.created_at)).total_seconds() // 60),
        )
        for ticket in tickets
        if ticket.status == TicketStatus.PENDIENTE
    ]
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
        unassigned_cases=sum(
            ticket.executive_id is None and ticket.status == TicketStatus.PENDIENTE
            for ticket in tickets
        ),
        automatic_resolved=automatic,
        human_routed=human,
        automatic_resolution_rate=round(automatic / len(tickets) * 100, 2) if tickets else 0,
        wait_p50_minutes=percentile_of(waits, 0.5),
        wait_p95_minutes=percentile_of(waits, 0.95),
        oldest_pending_minutes=max(pending_ages, default=0),
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
                version=executive.version,
                pending=workloads[executive.id][TicketStatus.PENDIENTE],
                in_attention=workloads[executive.id][TicketStatus.EN_ATENCION],
                closed=workloads[executive.id][TicketStatus.CERRADO],
            )
            for executive in executives
        ],
    )
