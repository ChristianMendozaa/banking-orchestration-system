from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.security import (
    create_access_token,
    hash_token,
    new_opaque_token,
    verify_password,
)
from app.db.models import RefreshSession, User
from app.db.session import get_db
from app.domain.schemas import LoginRequest, TokenResponse, UserSummary

router = APIRouter(prefix="/auth", tags=["Autenticacion"])
REFRESH_COOKIE = "orquestacion_refresh"


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_hours * 3600,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/",
    )


def _token_response(user: User, settings: Settings) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role.value, settings),
        expires_in=settings.access_token_minutes * 60,
        user=UserSummary.model_validate(user),
    )


async def _new_refresh(db: AsyncSession, user: User, settings: Settings) -> str:
    token = new_opaque_token()
    db.add(
        RefreshSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + timedelta(hours=settings.refresh_token_hours),
        )
    )
    return token


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    user = await db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not user.active or not verify_password(payload.password, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "Credenciales invalidas", 401)
    refresh = await _new_refresh(db, user, settings)
    await db.commit()
    _set_refresh_cookie(response, refresh, settings)
    return _token_response(user, settings)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    if not refresh_token:
        raise AppError("REFRESH_REQUIRED", "Falta el token de renovacion", 401)
    stored = await db.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == hash_token(refresh_token))
    )
    now = datetime.now(UTC)
    expiry = None
    if stored:
        expiry = (
            stored.expires_at if stored.expires_at.tzinfo else stored.expires_at.replace(tzinfo=UTC)
        )
    if not stored or stored.revoked_at or expiry < now:
        raise AppError("INVALID_REFRESH", "Sesion vencida o revocada", 401)
    user = await db.get(User, stored.user_id)
    if not user or not user.active:
        raise AppError("USER_NOT_FOUND", "Usuario inactivo o inexistente", 401)
    stored.revoked_at = now
    new_refresh = await _new_refresh(db, user, settings)
    await db.commit()
    _set_refresh_cookie(response, new_refresh, settings)
    return _token_response(user, settings)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    if refresh_token:
        stored = await db.scalar(
            select(RefreshSession).where(RefreshSession.token_hash == hash_token(refresh_token))
        )
        if stored and not stored.revoked_at:
            stored.revoked_at = datetime.now(UTC)
            await db.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/")


@router.get("/me", response_model=UserSummary)
async def me(user: User = Depends(get_current_user)) -> UserSummary:
    return UserSummary.model_validate(user)
