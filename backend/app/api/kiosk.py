from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_kiosk_session, get_openai_provider, get_orchestrator
from app.core.errors import AppError
from app.core.security import hash_token, new_opaque_token
from app.db.models import KioskSession
from app.db.session import get_db
from app.domain.enums import SessionStatus
from app.domain.schemas import (
    ConfirmationRequest,
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

router = APIRouter(prefix="/kiosk", tags=["Kiosco"])


@router.post("/sessions", response_model=SessionCreatedResponse, status_code=201)
async def create_session(
    payload: SessionCreateRequest, db: AsyncSession = Depends(get_db)
) -> SessionCreatedResponse:
    token = new_opaque_token()
    kiosk_session = KioskSession(
        access_token_hash=hash_token(token),
        status=SessionStatus.CREATED,
        preferential_attention=payload.preferential_attention,
    )
    db.add(kiosk_session)
    await db.commit()
    await db.refresh(kiosk_session)
    return SessionCreatedResponse(
        session_id=kiosk_session.id, session_token=token, status=kiosk_session.status
    )


@router.post("/sessions/{session_id}/realtime-token", response_model=RealtimeTokenResponse)
async def realtime_token(
    kiosk_session: KioskSession = Depends(get_kiosk_session),
    provider: OpenAIProvider | None = Depends(get_openai_provider),
    db: AsyncSession = Depends(get_db),
) -> RealtimeTokenResponse:
    if not provider:
        raise AppError("OPENAI_NOT_CONFIGURED", "El servicio de voz no esta configurado", 503)
    data = await provider.create_realtime_client_secret(str(kiosk_session.id))
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


@router.post("/sessions/{session_id}/confirmation", response_model=FlowResult)
async def confirm(
    payload: ConfirmationRequest,
    kiosk_session: KioskSession = Depends(get_kiosk_session),
    db: AsyncSession = Depends(get_db),
    orchestrator: OrchestratorService = Depends(get_orchestrator),
) -> FlowResult:
    response = await orchestrator.confirm(db, kiosk_session, payload.confirmed)
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
    result = None
    if kiosk_session.status in {SessionStatus.RESOLVED_AUTOMATIC, SessionStatus.ASSIGNED}:
        result = await orchestrator._build_result(db, kiosk_session.id)
    return SessionStatusResponse(
        session_id=kiosk_session.id,
        status=kiosk_session.status,
        resolution_type=kiosk_session.resolution_type,
        final_response=kiosk_session.final_response,
        result=result,
    )
