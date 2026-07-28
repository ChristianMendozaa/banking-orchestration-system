from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_roles
from app.core.config import Settings, get_settings
from app.core.datetime import ensure_aware
from app.core.errors import AppError
from app.db.models import (
    CaseRecord,
    Executive,
    OperationalAuditEvent,
    Ticket,
    TraceEvent,
    User,
)
from app.db.session import get_db
from app.domain.enums import CaseStatus, Category, ExecutiveStatus, Priority, TicketStatus, UserRole
from app.domain.schemas import (
    ExecutiveStatusResult,
    ExecutiveStatusUpdate,
    ExecutiveWorkload,
    HourlyMetric,
    ManagementCasesResponse,
    ManagementMetrics,
    ManagementTicketMutation,
    ManagerialCase,
    MetricSlice,
    TicketAssignmentUpdate,
    TicketPriorityUpdate,
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


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


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
        wait_p50_minutes=_percentile(waits, 0.5),
        wait_p95_minutes=_percentile(waits, 0.95),
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
    filters, _, _ = _filters(date_from, date_to, category, priority, executive_id)
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


async def _locked_ticket(db: AsyncSession, ticket_id: UUID) -> Ticket:
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


def _mutation_result(ticket: Ticket) -> ManagementTicketMutation:
    return ManagementTicketMutation(
        id=ticket.public_id,
        number=str(ticket.number),
        executive_id=ticket.executive_id,
        priority=ticket.case.priority,
        status=ticket.status,
        version=ticket.version,
    )


def _audit(
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
    _audit(
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
    ticket = await _locked_ticket(db, ticket_id)
    if ticket.version != payload.expected_version:
        raise AppError("VERSION_CONFLICT", "El ticket fue actualizado por otro proceso", 409)
    previous_id = ticket.executive_id
    if previous_id == payload.executive_id:
        return _mutation_result(ticket)

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
    _audit(
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
    return _mutation_result(ticket)


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
    ticket = await _locked_ticket(db, ticket_id)
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
    _audit(
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
    return _mutation_result(ticket)
