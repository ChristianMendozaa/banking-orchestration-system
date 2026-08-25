"""Nodes for `identification_graph`, the port of `OrchestratorService.identify`."""

from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import encrypt_identifier, hash_identifier, mask_identifier
from app.db.models import CaseRecord, ClientReference, Identification, TraceEvent
from app.domain.enums import IdentificationStatus, SessionStatus
from app.domain.schemas import IdentificationRequest
from app.services.graph.state import GraphContext, OrchestrationState


async def guard_identification(
    state: OrchestrationState, runtime: Runtime[GraphContext]
) -> Command:
    db = runtime.context.db
    kiosk_session = state["kiosk_session"]

    if kiosk_session.status in {SessionStatus.RESOLVED_AUTOMATIC, SessionStatus.ASSIGNED}:
        return Command(goto=END, update={"next_action": "BUILD_RESULT"})
    if kiosk_session.status != SessionStatus.AWAITING_IDENTIFICATION:
        raise AppError(
            "INVALID_SESSION_STATE",
            "La sesión no espera un CI",
            409,
            {"status": kiosk_session.status.value},
        )
    case = await runtime.context.repository.case_by_session(
        db, kiosk_session.id, with_identification=True, with_ticket=True
    )
    if not case:
        raise AppError("CASE_NOT_FOUND", "Primero confirma el requerimiento", 409)
    if case.ticket:
        return Command(goto=END, update={"case": case, "next_action": "BUILD_RESULT"})
    return Command(goto="resolve_client_reference", update={"case": case})


async def resolve_client_reference(
    state: OrchestrationState, runtime: Runtime[GraphContext]
) -> dict:
    return await resolve_identifier(
        runtime.context.db,
        state["identification_payload"],
        runtime.context.settings,
    )


async def resolve_identifier(
    db: AsyncSession,
    payload: IdentificationRequest,
    settings: Settings,
) -> dict:
    """Resolve an identifier for either the graph entry point or a planned sibling case."""
    identifier_hash = hash_identifier(payload.identifier, settings)
    client_reference = await db.scalar(
        select(ClientReference).where(
            ClientReference.identifier_hash == identifier_hash,
            ClientReference.active.is_(True),
        )
    )
    status = IdentificationStatus.IDENTIFICADO if client_reference else IdentificationStatus.FALLIDO
    return {
        "identifier_hash": identifier_hash,
        "client_reference_id": client_reference.id if client_reference else None,
        "identification_result_status": status,
    }


async def persist_identification(state: OrchestrationState, runtime: Runtime[GraphContext]) -> dict:
    await record_identification(
        runtime.context.db,
        state["case"],
        state["identification_payload"],
        state,
        runtime.context.settings,
    )
    return {}


async def record_identification(
    db: AsyncSession,
    case: CaseRecord,
    payload: IdentificationRequest,
    resolved: dict,
    settings: Settings,
) -> None:
    """Persist protected identification through one implementation for every case path."""
    status = resolved["identification_result_status"]
    client_reference_id = resolved["client_reference_id"]
    ciphertext, nonce, key_id = encrypt_identifier(payload.identifier, str(case.id), settings)
    existing = await db.scalar(select(Identification).where(Identification.case_id == case.id))
    if existing:
        existing.client_reference_id = client_reference_id
        existing.identifier_hash = resolved["identifier_hash"]
        existing.masked_identifier = mask_identifier(payload.identifier)
        existing.identifier_ciphertext = ciphertext
        existing.identifier_nonce = nonce
        existing.identifier_key_id = key_id
        existing.status = status
    else:
        db.add(
            Identification(
                case_id=case.id,
                client_reference_id=client_reference_id,
                identifier_hash=resolved["identifier_hash"],
                masked_identifier=mask_identifier(payload.identifier),
                identifier_ciphertext=ciphertext,
                identifier_nonce=nonce,
                identifier_key_id=key_id,
                status=status,
            )
        )
    case.identification_status = status
    db.add(
        TraceEvent(
            case_id=case.id,
            event_type="CLIENT_IDENTIFICATION",
            description=f"Identificacion de cliente: {status.value}",
        )
    )
