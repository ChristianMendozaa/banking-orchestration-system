"""Executive ticket endpoints: the queue, one ticket, the identifier reveal, and
the status transitions that move a ticket through attention.
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.api.tickets.queries import (
    authorized_ticket,
    search_filter,
    ticket_list_options,
)
from app.api.tickets.serializers import (
    case_identification,
    ticket_detail_response,
    ticket_item,
)
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.security import decrypt_identifier
from app.db.models import (
    CaseRecord,
    Identification,
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
    IdentifierRevealResponse,
    TicketDetail,
    TicketPage,
    TicketStatusUpdate,
)
from app.services.pii import PIIMaskingService

router = APIRouter(tags=["Operacion ejecutiva"])


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
        filters.append(search_filter(q))

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
                .options(*ticket_list_options())
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


@router.get("/tickets/{ticket_id}", response_model=TicketDetail)
async def ticket_detail(
    ticket_id: UUID,
    user: User = Depends(require_roles(UserRole.EXECUTIVE, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TicketDetail:
    ticket = await authorized_ticket(db, ticket_id, user)
    return ticket_detail_response(ticket, user, settings)


@router.post("/tickets/{ticket_id}/identifier/reveal", response_model=IdentifierRevealResponse)
async def reveal_identifier(
    ticket_id: UUID,
    response: Response,
    user: User = Depends(require_roles(UserRole.EXECUTIVE)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> IdentifierRevealResponse:
    ticket = await authorized_ticket(db, ticket_id, user, for_update=True)
    if ticket.status != TicketStatus.EN_ATENCION:
        raise AppError(
            "IDENTIFIER_REVEAL_NOT_ALLOWED",
            "El CI completo solo puede revelarse durante la atención activa",
            409,
        )
    identification = case_identification(ticket)
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
    ticket = await authorized_ticket(db, ticket_id, user, for_update=True)
    if ticket.automatic:
        raise AppError("AUTOMATIC_TICKET", "Un ticket automatico no admite cambios", 409)
    if ticket.version != payload.expected_version:
        raise AppError("VERSION_CONFLICT", "El ticket fue actualizado por otro proceso", 409)
    if payload.status == ticket.status:
        return ticket_detail_response(ticket, user, settings)
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
        identification = case_identification(ticket)
        if identification and any(
            (
                identification.identifier_ciphertext,
                identification.identifier_nonce,
                identification.identifier_key_id,
            )
        ):
            identification.identifier_ciphertext = None
            identification.identifier_nonce = None
            identification.identifier_key_id = None
            db.add(
                TraceEvent(
                    case_id=ticket.case_id,
                    event_type="CLIENT_IDENTIFIER_RECOVERY_PURGED",
                    description="El CI recuperable fue eliminado al cerrar la atención",
                    metadata_json={"user_id": str(user.id)},
                )
            )
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
    refreshed = await authorized_ticket(db, ticket_id, user)
    return ticket_detail_response(refreshed, user, settings)
