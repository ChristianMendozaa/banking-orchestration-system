"""Bearer-token auth for the MCP server.

Reuses the same JWT + role model the staff REST API uses (`decode_access_token`,
`app.db.models.User`, `UserRole.EXECUTIVE` / `UserRole.MANAGER`) rather than inventing a
parallel scheme, per the architecture decision to keep MCP auth boring and consistent.
`app.api.deps.get_current_user` / `require_roles` do the equivalent check as FastAPI
dependencies; this ASGI app sits outside that dependency-injection system, so the same
logic is inlined here as a raw ASGI middleware instead of Starlette's `BaseHTTPMiddleware`
(which buffers the response body and is unsafe for a streaming transport like MCP's
streamable-http).
"""

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.db.models import User
from app.domain.enums import UserRole

_STAFF_ROLES = {UserRole.EXECUTIVE, UserRole.MANAGER}
_EXEMPT_PATHS = {"/healthz"}


class BearerAuthMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: Settings,
        session_factory: async_sessionmaker,
    ) -> None:
        self._app = app
        self._settings = settings
        self._session_factory = session_factory

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in _EXEMPT_PATHS:
            await self._app(scope, receive, send)
            return
        token = _bearer_token(scope)
        if not token:
            await _reject(send, "AUTH_REQUIRED", "Se requiere autenticacion", 401)
            return
        try:
            await self._authenticate(token)
        except AppError as exc:
            await _reject(send, exc.code, exc.message, exc.status_code)
            return
        await self._app(scope, receive, send)

    async def _authenticate(self, token: str) -> User:
        payload = decode_access_token(token, self._settings)
        try:
            user_id = UUID(payload["sub"])
        except (KeyError, ValueError, TypeError) as exc:
            raise AppError("INVALID_TOKEN", "Token de acceso invalido", 401) from exc
        async with self._session_factory() as db:
            user = await db.scalar(select(User).where(User.id == user_id, User.active.is_(True)))
        if not user:
            raise AppError("USER_NOT_FOUND", "Usuario inactivo o inexistente", 401)
        if user.role not in _STAFF_ROLES:  # pragma: no cover
            # UserRole currently has exactly EXECUTIVE and MANAGER, both in
            # _STAFF_ROLES, so this branch is unreachable today. Kept -- not deleted
            # -- as a guard against a future third role being added without an
            # explicit decision about MCP access; see require_roles() in
            # app/api/deps.py for the equivalent pattern on the REST API.
            raise AppError("FORBIDDEN", "No tiene permisos para esta operacion", 403)
        return user


def _bearer_token(scope: Scope) -> str | None:
    headers = dict(scope.get("headers") or [])
    raw = headers.get(b"authorization", b"").decode("latin-1")
    if not raw.startswith("Bearer "):
        return None
    token = raw.removeprefix("Bearer ").strip()
    return token or None


async def _reject(send: Send, code: str, message: str, status: int) -> None:
    body = json.dumps({"code": code, "message": message}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})
