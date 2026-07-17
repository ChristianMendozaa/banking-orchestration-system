from collections.abc import Callable
from functools import lru_cache
from uuid import UUID

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.security import decode_access_token, hash_token
from app.db.models import KioskSession, User
from app.db.session import get_db
from app.domain.enums import UserRole
from app.knowledge.service import KnowledgeService
from app.services.agents import (
    ClassificationAgent,
    DerivationAgent,
    InitialAttentionAgent,
    PrioritizationAgent,
)
from app.services.openai_provider import OpenAIProvider
from app.services.orchestrator import OrchestratorService
from app.services.pii import PIIMaskingService

bearer = HTTPBearer(auto_error=False)


@lru_cache
def get_openai_provider() -> OpenAIProvider | None:
    settings = get_settings()
    return OpenAIProvider(settings) if settings.openai_enabled else None


@lru_cache
def get_orchestrator() -> OrchestratorService:
    settings = get_settings()
    provider = get_openai_provider()
    return OrchestratorService(
        settings=settings,
        pii=PIIMaskingService(),
        classifier=ClassificationAgent(settings, provider),
        prioritizer=PrioritizationAgent(),
        derivation=DerivationAgent(provider),
        initial_attention=InitialAttentionAgent(KnowledgeService(settings, provider)),
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if not credentials:
        raise AppError("AUTH_REQUIRED", "Se requiere autenticacion", 401)
    payload = decode_access_token(credentials.credentials, settings)
    try:
        user_id = UUID(payload["sub"])
    except (ValueError, TypeError) as exc:
        raise AppError("INVALID_TOKEN", "Token de acceso invalido", 401) from exc
    user = await db.scalar(select(User).where(User.id == user_id, User.active.is_(True)))
    if not user:
        raise AppError("USER_NOT_FOUND", "Usuario inactivo o inexistente", 401)
    return user


def require_roles(*roles: UserRole) -> Callable:
    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise AppError("FORBIDDEN", "No tiene permisos para esta operacion", 403)
        return user

    return dependency


async def get_kiosk_session(
    session_id: UUID,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    db: AsyncSession = Depends(get_db),
) -> KioskSession:
    if not x_session_token:
        raise AppError("SESSION_TOKEN_REQUIRED", "Falta el token de la sesion", 401)
    kiosk_session = await db.scalar(
        select(KioskSession).where(
            KioskSession.id == session_id,
            KioskSession.access_token_hash == hash_token(x_session_token),
        )
    )
    if not kiosk_session:
        raise AppError("SESSION_NOT_FOUND", "Sesion inexistente o token invalido", 404)
    return kiosk_session
