"""The kiosk's spoken channel.

One WebSocket carries everything a voice turn needs: microphone audio up, and transcripts,
flow results and synthesised speech down. It exists on the backend rather than in the
browser because the backend already holds the OpenAI credentials, the orchestrator and the
session state -- putting the audio here removes the browser's need for any of them.
"""

import logging
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, Query, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.websockets import WebSocketDisconnect

from app.api.deps import (
    get_openai_provider,
    get_orchestrator,
    get_session_factory,
    resolve_kiosk_session,
)
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.services.openai_provider import OpenAIProvider
from app.services.orchestrator import OrchestratorService
from app.services.voice.session import KioskVoiceSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kiosk", tags=["Kiosco"])

# Close codes. 1008 is the WebSocket "policy violation" code, which is the closest thing the
# protocol has to a 401/403 -- a handshake cannot carry a JSON error body.
CLOSE_POLICY_VIOLATION = 1008
CLOSE_INTERNAL_ERROR = 1011


def origin_allowed(origin: str | None, settings: Settings) -> bool:
    """Whether a handshake from `origin` may open a voice session.

    CORSMiddleware does not apply to WebSocket upgrades, so the same-origin rule the HTTP
    API gets for free has to be enforced by hand here. A missing Origin header means the
    request did not come from a browser; the session token still has to be valid, but there
    is no origin to check against.
    """
    if origin is None:
        return True
    if "*" in settings.cors_origins:
        return True
    return any(
        urlparse(origin).netloc == urlparse(allowed).netloc
        and urlparse(origin).scheme == urlparse(allowed).scheme
        for allowed in settings.cors_origins
    )


@router.websocket("/sessions/{session_id}/voice")
async def voice_channel(
    websocket: WebSocket,
    session_id: UUID,
    token: str = Query(..., min_length=1),
    settings: Settings = Depends(get_settings),
    orchestrator: OrchestratorService = Depends(get_orchestrator),
    provider: OpenAIProvider | None = Depends(get_openai_provider),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> None:
    if not origin_allowed(websocket.headers.get("origin"), settings):
        await websocket.close(code=CLOSE_POLICY_VIOLATION, reason="ORIGIN_NOT_ALLOWED")
        return
    if provider is None:
        await websocket.close(code=CLOSE_POLICY_VIOLATION, reason="OPENAI_NOT_CONFIGURED")
        return

    # Authenticate before accepting, so an invalid token never gets an open socket. The
    # token arrives as a query parameter because a browser cannot set headers on a
    # WebSocket handshake; `resolve_kiosk_session` is the same rule the HTTP API applies.
    try:
        async with session_factory() as db:
            await resolve_kiosk_session(db, session_id, token)
    except AppError as exc:
        await websocket.close(code=CLOSE_POLICY_VIOLATION, reason=exc.code)
        return

    await websocket.accept()
    session = KioskVoiceSession(
        websocket=websocket,
        session_id=session_id,
        token=token,
        orchestrator=orchestrator,
        provider=provider,
        settings=settings,
        session_factory=session_factory,
    )
    try:
        await session.run()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("kiosk voice session failed", extra={"session_id": str(session_id)})
        try:
            await websocket.close(code=CLOSE_INTERNAL_ERROR, reason="VOICE_SESSION_FAILED")
        except RuntimeError:
            pass
