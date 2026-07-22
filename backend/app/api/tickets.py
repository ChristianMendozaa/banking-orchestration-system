from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import String, case, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_roles
from app.core.config import Settings, get_settings
from app.core.datetime import ensure_aware
from app.core.errors import AppError
from app.core.security import decrypt_identifier
from app.db.models import (
    CaseRecord,
    ClientReference,
    Identification,
    KioskSession,
    Ticket,
    TraceEvent,
    User,
)
from app.db.session import get_db
from app.domain.enums import (
    CaseStatus,
    Category,
    ExecutiveStatus,
    Priority,
    TicketStatus,
    UserRole,
)
from app.domain.schemas import (
    ConversationMessageOut,
    IdentifierRevealResponse,
    ProtectedIdentity,
    TicketDetail,
    TicketListItem,
    TicketPage,
    TicketStatusUpdate,
    TraceEventOut,
)
from app.services.pii import PIIMaskingService

router = APIRouter(tags=["Operacion ejecutiva"])


def _identity(ticket: Ticket) -> Identification | None:
    return ticket.case.identification


def ticket_item(ticket: Ticket, *, include_client_name: bool) -> TicketListItem:
    now = datetime.now(UTC)
    assigned = ensure_aware(ticket.assigned_at) if ticket.assigned_at else None
    elapsed = max(
        0, int((now - (assigned or ensure_aware(ticket.created_at))).total_seconds() // 60)
    )
    started = ensure_aware(ticket.started_at) if ticket.started_at else None
    wait = max(0, int(((started or now) - ensure_aware(ticket.created_at)).total_seconds() // 60))
    executive = ticket.executive
    case_record = ticket.case
    identification = _identity(ticket)
    reference = identification.client_reference if identification else None
    return TicketListItem(
        id=ticket.public_id,
        number=str(ticket.number),
        category=case_record.category,
        priority=case_record.priority,
        summary=case_record.summary,
        time_assigned=assigned,
        minutes_elapsed=elapsed,
        executive_name=executive.display_name if executive else None,
        executive_title=executive.title if executive else None,
        window_number=executive.window_number if executive else None,
        status=ticket.status,
        client_session_id=f"SES-****-{str(case_record.session_id)[-4:].upper()}",
        wait_time_min=wait,
        estimated_wait_minutes=ticket.estimated_wait_minutes,
        identification_status=case_record.identification_status,
        preferential_attention=case_record.preferential_attention,
        client_display_name=(reference.display_name if include_client_name and reference else None),
        masked_identifier=identification.masked_identifier if identification else None,
        started_at=ticket.started_at,
        closed_at=ticket.closed_at,
        resolution_outcome=ticket.resolution_outcome,
        version=ticket.version,
    )


def _identity_option():
    return (
        selectinload(Ticket.case)
        .selectinload(CaseRecord.identification)
        .selectinload(Identification.client_reference)
    )


def _ticket_list_options():
    return (selectinload(Ticket.case), _identity_option(), selectinload(Ticket.executive))


def _ticket_detail_options():
    return (
        *_ticket_list_options(),
        selectinload(Ticket.case).selectinload(CaseRecord.events),
        selectinload(Ticket.case)
        .selectinload(CaseRecord.session)
        .selectinload(KioskSession.conversation_messages),
    )


def _search_filter(value: str):
    pattern = f"%{value.strip()}%"
    return or_(
        cast(Ticket.number, String).ilike(pattern),
        CaseRecord.summary.ilike(pattern),
        ClientReference.display_name.ilike(pattern),
        Identification.masked_identifier.ilike(pattern),
    )


@router.get("/executive/tickets", response_model=TicketPage)
async def executive_tickets(
    status: TicketStatus | None = None,
    category: Category | None = None,
    priority: Priority | None = None,
    q: str | None = Query(default=None, max_length=120),
    sort: Literal["priority", "oldest", "newest"] = "priority",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_roles(UserRole.EXECUTIVE)),
    db: AsyncSession = Depends(get_db),
) -> TicketPage:
    if not user.executive_id:
        raise AppError("EXECUTIVE_PROFILE_MISSING", "El usuario no tiene perfil ejecutivo", 409)
    filters = [Ticket.executive_id == user.executive_id]
    if category:
        filters.append(CaseRecord.category == category)
    if priority:
        filters.append(CaseRecord.priority == priority)
    if q and q.strip():
        filters.append(_search_filter(q))

    joined = (
        select(Ticket)
        .join(Ticket.case)
        .outerjoin(CaseRecord.identification)
        .outerjoin(Identification.client_reference)
    )
    count_query = (
        select(Ticket.status, func.count(Ticket.number))
        .join(Ticket.case)
        .outerjoin(CaseRecord.identification)
        .outerjoin(Identification.client_reference)
        .where(*filters)
        .group_by(Ticket.status)
    )
    counts = {ticket_status: 0 for ticket_status in TicketStatus}
    for ticket_status, count in (await db.execute(count_query)).all():
        counts[ticket_status] = count

    page_filters = [*filters]
    if status:
        page_filters.append(Ticket.status == status)
    total = sum(counts.values()) if status is None else counts[status]
    priority_order = case(
        (CaseRecord.priority == Priority.CRITICO, 0),
        (CaseRecord.priority == Priority.ALTO, 1),
        (CaseRecord.priority == Priority.MEDIO, 2),
        else_=3,
    )
    order = {
        "priority": (priority_order, Ticket.created_at),
        "oldest": (Ticket.created_at,),
        "newest": (Ticket.created_at.desc(),),
    }[sort]
    tickets = list(
        (
            await db.scalars(
                joined.where(*page_filters)
                .options(*_ticket_list_options())
                .order_by(*order)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .unique()
        .all()
    )
    return TicketPage(
        items=[ticket_item(ticket, include_client_name=True) for ticket in tickets],
        page=page,
        page_size=page_size,
        total=total,
        status_counts=counts,
    )


async def _authorized_ticket(
    db: AsyncSession,
    public_id: UUID,
    user: User,
    *,
    for_update: bool = False,
) -> Ticket:
    statement = (
        select(Ticket).where(Ticket.public_id == public_id).options(*_ticket_detail_options())
    )
    if for_update and db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    ticket = await db.scalar(statement)
    if not ticket:
        raise AppError("TICKET_NOT_FOUND", "Ticket inexistente", 404)
    if user.role == UserRole.EXECUTIVE and ticket.executive_id != user.executive_id:
        raise AppError("FORBIDDEN", "El ticket pertenece a otro ejecutivo", 403)
    return ticket


def _ticket_detail(ticket: Ticket, user: User, settings: Settings) -> TicketDetail:
    identification = _identity(ticket)
    reference = identification.client_reference if identification else None
    cutoff = datetime.now(UTC) - timedelta(days=settings.conversation_retention_days)
    messages = [
        ConversationMessageOut.model_validate(message)
        for message in ticket.case.session.conversation_messages
        if ensure_aware(message.created_at) >= cutoff
    ]
    is_executive = user.role == UserRole.EXECUTIVE
    item = ticket_item(ticket, include_client_name=is_executive)
    return TicketDetail(
        **item.model_dump(),
        consultation_level=ticket.case.consultation_level,
        identity=ProtectedIdentity(
            status=ticket.case.identification_status,
            display_name=reference.display_name if is_executive and reference else None,
            masked_identifier=identification.masked_identifier if identification else None,
            reveal_available=bool(
                is_executive
                and identification
                and identification.identifier_ciphertext
                and identification.identifier_nonce
                and identification.identifier_key_id
            ),
        ),
        conversation=messages,
        events=[TraceEventOut.model_validate(event) for event in ticket.case.events],
        resolution_note=ticket.resolution_note,
    )


@router.get("/tickets/{ticket_id}", response_model=TicketDetail)
async def ticket_detail(
    ticket_id: UUID,
    user: User = Depends(require_roles(UserRole.EXECUTIVE, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TicketDetail:
    ticket = await _authorized_ticket(db, ticket_id, user)
    return _ticket_detail(ticket, user, settings)


@router.post("/tickets/{ticket_id}/identifier/reveal", response_model=IdentifierRevealResponse)
async def reveal_identifier(
    ticket_id: UUID,
    response: Response,
    user: User = Depends(require_roles(UserRole.EXECUTIVE)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> IdentifierRevealResponse:
    ticket = await _authorized_ticket(db, ticket_id, user, for_update=True)
    identification = _identity(ticket)
    if not identification or not all(
        (
            identification.identifier_ciphertext,
            identification.identifier_nonce,
            identification.identifier_key_id,
        )
    ):
        raise AppError(
            "IDENTIFIER_NOT_RECOVERABLE",
            "El CI completo no esta disponible para este caso historico",
            409,
        )
    identifier = decrypt_identifier(
        identification.identifier_ciphertext,
        identification.identifier_nonce,
        identification.identifier_key_id,
        str(ticket.case_id),
        settings,
    )
    db.add(
        TraceEvent(
            case_id=ticket.case_id,
            event_type="CLIENT_IDENTIFIER_REVEALED",
            description="El ejecutivo asignado consultó el CI completo",
            metadata_json={"user_id": str(user.id)},
        )
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return IdentifierRevealResponse(identifier=identifier)


@router.patch("/tickets/{ticket_id}/status", response_model=TicketDetail)
async def update_ticket_status(
    ticket_id: UUID,
    payload: TicketStatusUpdate,
    user: User = Depends(require_roles(UserRole.EXECUTIVE)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TicketDetail:
    ticket = await _authorized_ticket(db, ticket_id, user, for_update=True)
    if ticket.automatic:
        raise AppError("AUTOMATIC_TICKET", "Un ticket automatico no admite cambios", 409)
    if ticket.version != payload.expected_version:
        raise AppError("VERSION_CONFLICT", "El ticket fue actualizado por otro proceso", 409)
    if payload.status == ticket.status:
        return _ticket_detail(ticket, user, settings)
    allowed = {
        TicketStatus.PENDIENTE: {TicketStatus.EN_ATENCION},
        TicketStatus.EN_ATENCION: {TicketStatus.CERRADO},
        TicketStatus.CERRADO: set(),
    }
    if payload.status not in allowed[ticket.status]:
        raise AppError("INVALID_STATUS_TRANSITION", "Cambio de estado no permitido", 409)

    now = datetime.now(UTC)
    metadata: dict[str, str] = {"user_id": str(user.id)}
    if payload.status == TicketStatus.EN_ATENCION:
        other = await db.scalar(
            select(Ticket).where(
                Ticket.executive_id == ticket.executive_id,
                Ticket.status == TicketStatus.EN_ATENCION,
                Ticket.number != ticket.number,
            )
        )
        if other:
            raise AppError(
                "EXECUTIVE_ALREADY_ATTENDING",
                "Ya existe otro caso en atención",
                409,
                {"ticket_id": str(other.public_id), "ticket_number": str(other.number)},
            )
        ticket.started_at = now
        if ticket.executive:
            ticket.executive.status = ExecutiveStatus.OCUPADO
    else:
        if payload.resolution_outcome is None or payload.resolution_note is None:
            raise AppError(
                "RESOLUTION_REQUIRED",
                "Debe registrar el resultado y una nota antes de cerrar",
                422,
            )
        masked_note = PIIMaskingService().mask(payload.resolution_note).masked_text
        ticket.closed_at = now
        ticket.resolution_outcome = payload.resolution_outcome
        ticket.resolution_note = masked_note
        ticket.case.status = CaseStatus.CLOSED
        if ticket.executive and ticket.executive.status != ExecutiveStatus.INACTIVO:
            ticket.executive.status = ExecutiveStatus.DISPONIBLE
        metadata["resolution_outcome"] = payload.resolution_outcome.value

    ticket.status = payload.status
    ticket.version += 1
    db.add(
        TraceEvent(
            case_id=ticket.case_id,
            event_type="TICKET_STATUS_UPDATED",
            description=f"Estado de ticket actualizado a {payload.status.value}",
            metadata_json=metadata,
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AppError(
            "EXECUTIVE_ALREADY_ATTENDING",
            "Ya existe otro caso en atención",
            409,
        ) from exc
    refreshed = await _authorized_ticket(db, ticket_id, user)
    return _ticket_detail(refreshed, user, settings)
