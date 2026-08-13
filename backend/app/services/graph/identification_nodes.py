"""Nodes for `identification_graph`, the port of `OrchestratorService.identify`."""

from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command
from sqlalchemy import select

from app.core.errors import AppError
from app.core.security import encrypt_identifier, hash_identifier, mask_identifier
from app.db.models import ClientReference, Identification, TraceEvent
from app.domain.enums import IdentificationStatus, SessionStatus
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
    db = runtime.context.db
    payload = state["identification_payload"]
    identifier_hash = hash_identifier(payload.identifier, runtime.context.settings)
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
    db = runtime.context.db
    payload = state["identification_payload"]
    case = state["case"]
    status = state["identification_result_status"]
    client_reference_id = state["client_reference_id"]
    ciphertext, nonce, key_id = encrypt_identifier(
        payload.identifier, str(case.id), runtime.context.settings
    )
    if case.identification:
        case.identification.client_reference_id = client_reference_id
        case.identification.identifier_hash = state["identifier_hash"]
        case.identification.masked_identifier = mask_identifier(payload.identifier)
        case.identification.identifier_ciphertext = ciphertext
        case.identification.identifier_nonce = nonce
        case.identification.identifier_key_id = key_id
        case.identification.status = status
    else:
        db.add(
            Identification(
                case_id=case.id,
                client_reference_id=client_reference_id,
                identifier_hash=state["identifier_hash"],
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
    return {}
