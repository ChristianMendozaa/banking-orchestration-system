from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_kiosk_session, get_openai_provider, get_orchestrator
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import hash_token, new_opaque_token
from app.db.models import ConversationMessage, KioskSession
from app.db.session import get_db
from app.domain.enums import SessionStatus
from app.domain.schemas import (
    ConfirmationRequest,
    ConversationSyncRequest,
    ConversationSyncResponse,
    FlowResult,
    IdentificationRequest,
    RealtimeTokenResponse,
    SessionCreatedResponse,
    SessionCreateRequest,
    SessionStatusResponse,
    TurnAnalysisResponse,
    TurnRequest,
)
from app.services.openai_provider import OpenAIProvider
from app.services.orchestrator import OrchestratorService
from app.services.pii import PIIMaskingService

router = APIRouter(prefix="/kiosk", tags=["Kiosco"])


@router.post("/sessions", response_model=SessionCreatedResponse, status_code=201)
async def create_session(
    payload: SessionCreateRequest,
    db: AsyncSession = Depends(get_db),
    settings=Depends(get_settings),
) -> SessionCreatedResponse:
    token = new_opaque_token()
    kiosk_session = KioskSession(
        access_token_hash=hash_token(token),
        status=SessionStatus.CREATED,
        preferential_attention=payload.preferential_attention,
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.kiosk_session_minutes),
    )
    db.add(kiosk_session)
    await db.commit()
    await db.refresh(kiosk_session)
    return SessionCreatedResponse(
        session_id=kiosk_session.id,
        session_token=token,
        status=kiosk_session.status,
        expires_at=kiosk_session.expires_at,
    )


@router.post("/sessions/{session_id}/realtime-token", response_model=RealtimeTokenResponse)
async def realtime_token(
    kiosk_session: KioskSession = Depends(get_kiosk_session),
    provider: OpenAIProvider | None = Depends(get_openai_provider),
    db: AsyncSession = Depends(get_db),
) -> RealtimeTokenResponse:
    if not provider:
        raise AppError("OPENAI_NOT_CONFIGURED", "El servicio de voz no esta configurado", 503)
    if kiosk_session.status not in {
        SessionStatus.CREATED,
        SessionStatus.LISTENING,
        SessionStatus.NEEDS_CLARIFICATION,
        SessionStatus.AWAITING_CONFIRMATION,
        SessionStatus.AWAITING_IDENTIFICATION,
    }:
        raise AppError(
            "INVALID_SESSION_STATE",
            "La sesion no admite iniciar el canal de voz en su estado actual",
            409,
        )
    data = await provider.create_realtime_client_secret(str(kiosk_session.id))
    if kiosk_session.status == SessionStatus.CREATED:
        kiosk_session.status = SessionStatus.LISTENING
    await db.commit()
    return RealtimeTokenResponse.model_validate(data)


@router.post("/sessions/{session_id}/turns", response_model=TurnAnalysisResponse)
async def analyze_turn(
    payload: TurnRequest,
    kiosk_session: KioskSession = Depends(get_kiosk_session),
    db: AsyncSession = Depends(get_db),
    orchestrator: OrchestratorService = Depends(get_orchestrator),
) -> TurnAnalysisResponse:
    response = await orchestrator.analyze_turn(db, kiosk_session, payload)
    await db.commit()
    return response


@router.post(
    "/sessions/{session_id}/conversation/messages",
    response_model=ConversationSyncResponse,
)
async def sync_conversation(
    payload: ConversationSyncRequest,
    kiosk_session: KioskSession = Depends(get_kiosk_session),
    db: AsyncSession = Depends(get_db),
) -> ConversationSyncResponse:
    item_ids = [message.item_id for message in payload.messages]
    existing = set(
        (
            await db.scalars(
                select(ConversationMessage.external_item_id).where(
                    ConversationMessage.session_id == kiosk_session.id,
                    ConversationMessage.external_item_id.in_(item_ids),
                )
            )
        ).all()
    )
    pii = PIIMaskingService()
    created = 0
    for message in payload.messages:
        if message.item_id in existing:
            continue
        db.add(
            ConversationMessage(
                session_id=kiosk_session.id,
                external_item_id=message.item_id,
                role=message.role,
                masked_text=pii.mask(message.text).masked_text,
            )
        )
        created += 1
    await db.commit()
    return ConversationSyncResponse(accepted=created)


@router.post("/sessions/{session_id}/confirmation", response_model=FlowResult)
async def confirm(
    payload: ConfirmationRequest,
    kiosk_session: KioskSession = Depends(get_kiosk_session),
    db: AsyncSession = Depends(get_db),
    orchestrator: OrchestratorService = Depends(get_orchestrator),
) -> FlowResult:
    response = await orchestrator.confirm(db, kiosk_session, payload)
    await db.commit()
    return response


@router.post("/sessions/{session_id}/identification", response_model=FlowResult)
async def identify(
    payload: IdentificationRequest,
    kiosk_session: KioskSession = Depends(get_kiosk_session),
    db: AsyncSession = Depends(get_db),
    orchestrator: OrchestratorService = Depends(get_orchestrator),
) -> FlowResult:
    response = await orchestrator.identify(db, kiosk_session, payload)
    await db.commit()
    return response


@router.get("/sessions/{session_id}", response_model=SessionStatusResponse)
async def get_session_status(
    kiosk_session: KioskSession = Depends(get_kiosk_session),
    db: AsyncSession = Depends(get_db),
    orchestrator: OrchestratorService = Depends(get_orchestrator),
) -> SessionStatusResponse:
    return await orchestrator.build_session_status(db, kiosk_session)
