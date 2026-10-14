"""Executive ticket endpoints: the queue, one ticket, the identifier reveal, the
status transitions that move a ticket through attention, and the derivation that
hands it to a colleague.
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_derivation_agent, require_roles
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
    Executive,
    Identification,
    Ticket,
    TraceEvent,
    User,
)
from app.db.repositories import ExecutiveRepository
from app.db.session import get_db
from app.domain.enums import (
    CaseStatus,
    Category,
    ExecutiveStatus,
    Priority,
    ResolutionOutcome,
    TicketStatus,
    UserRole,
)
from app.domain.schemas import (
    DerivationCandidate,
    DerivationCandidatesResponse,
    IdentifierRevealResponse,
    TicketDerivationRequest,
    TicketDerivationResult,
    TicketDetail,
    TicketPage,
    TicketStatusUpdate,
)
from app.services.agents import DerivationAgent
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
        if payload.resolution_outcome == ResolutionOutcome.DERIVADO:
            # Closing with this label used to end the case without anyone receiving it.
            raise AppError(
                "DERIVATION_REQUIRED",
                "Para derivar el caso use la derivación a otro ejecutivo",
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


@router.get(
    "/tickets/{ticket_id}/derivation/candidates",
    response_model=DerivationCandidatesResponse,
)
async def derivation_candidates(
    ticket_id: UUID,
    user: User = Depends(require_roles(UserRole.EXECUTIVE)),
    db: AsyncSession = Depends(get_db),
) -> DerivationCandidatesResponse:
    ticket = await authorized_ticket(db, ticket_id, user)
    repository = ExecutiveRepository()
    executives = await repository.transfer_candidates(db, exclude_id=ticket.executive_id)
    loads = await repository.active_loads(db)
    return DerivationCandidatesResponse(
        items=[
            DerivationCandidate(
                id=executive.id,
                name=executive.display_name,
                title=executive.title,
                window_number=executive.window_number,
                status=executive.status,
                active_load=loads[executive.id],
            )
            for executive in executives
        ]
    )


@router.post("/tickets/{ticket_id}/derivation", response_model=TicketDerivationResult)
async def derive_ticket(
    ticket_id: UUID,
    payload: TicketDerivationRequest,
    user: User = Depends(require_roles(UserRole.EXECUTIVE)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    derivation: DerivationAgent = Depends(get_derivation_agent),
) -> TicketDerivationResult:
    ticket = await authorized_ticket(db, ticket_id, user, for_update=True)
    if ticket.automatic:
        raise AppError("AUTOMATIC_TICKET", "Un ticket automatico no admite cambios", 409)
    if ticket.version != payload.expected_version:
        raise AppError("VERSION_CONFLICT", "El ticket fue actualizado por otro proceso", 409)
    if ticket.status == TicketStatus.CERRADO:
        raise AppError("INVALID_STATUS_TRANSITION", "Un caso cerrado no puede derivarse", 409)

    previous = ticket.executive
    automatic = payload.executive_id is None
    metadata: dict[str, object] = {
        "user_id": str(user.id),
        "previous_executive_id": str(previous.id) if previous else None,
        "mode": "AUTOMATIC" if automatic else "MANUAL",
    }
    target: Executive | None = None
    active_load = 0
    if automatic:
        routing = await derivation.rederive(
            db,
            ticket.case.category,
            ticket.case.summary,
            exclude_executive_id=ticket.executive_id,
        )
        if routing:
            target = routing.executive
            active_load = routing.active_load
            metadata.update(
                score=round(routing.score, 4),
                semantic_score=round(routing.semantic_score, 4),
                experience_score=round(routing.experience_score, 4),
                load_score=round(routing.load_score, 4),
            )
    else:
        if payload.executive_id == ticket.executive_id:
            raise AppError(
                "DERIVATION_TARGET_INVALID",
                "El caso ya está asignado a este ejecutivo",
                422,
            )
        statement = select(Executive).where(Executive.id == payload.executive_id)
        if db.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        target = await db.scalar(statement)
        if not target:
            raise AppError("EXECUTIVE_NOT_FOUND", "Ejecutivo inexistente", 404)
        if target.status == ExecutiveStatus.INACTIVO:
            raise AppError(
                "EXECUTIVE_NOT_AVAILABLE",
                "El ejecutivo seleccionado no está disponible",
                409,
            )
        active_load = (await ExecutiveRepository().active_loads(db))[target.id]

    now = datetime.now(UTC)
    if (
        ticket.status == TicketStatus.EN_ATENCION
        and previous
        and previous.status != ExecutiveStatus.INACTIVO
    ):
        previous.status = ExecutiveStatus.DISPONIBLE
    ticket.status = TicketStatus.PENDIENTE
    ticket.started_at = None
    ticket.version += 1
    if target:
        # Busy or not, the receiving executive keeps the ticket queued until they are free.
        ticket.executive_id = target.id
        ticket.assigned_at = now
        ticket.estimated_wait_minutes = (active_load + 1) * settings.estimated_service_minutes
        target.last_assigned_at = now
        ticket.case.status = CaseStatus.ASSIGNED
        destination = f"a {target.display_name}"
    else:
        ticket.executive_id = None
        ticket.assigned_at = None
        ticket.estimated_wait_minutes = None
        ticket.case.status = CaseStatus.QUEUED
        destination = "a la cola sin asignar por falta de un ejecutivo que lo reciba"
    metadata["new_executive_id"] = str(target.id) if target else None
    masked_note = PIIMaskingService().mask(payload.note).masked_text
    origin = f" de {previous.display_name}" if previous else ""
    db.add(
        TraceEvent(
            case_id=ticket.case_id,
            event_type="TICKET_DERIVED",
            description=f"Caso derivado{origin} {destination}. Motivo: {masked_note}",
            metadata_json=metadata,
        )
    )
    result = TicketDerivationResult(
        id=ticket.public_id,
        number=str(ticket.number),
        status=ticket.status,
        executive_id=target.id if target else None,
        executive_name=target.display_name if target else None,
        executive_title=target.title if target else None,
        window_number=target.window_number if target else None,
        estimated_wait_minutes=ticket.estimated_wait_minutes,
        automatic=automatic,
    )
    await db.commit()
    return result
