"""Tests for the MCP transport plumbing: auth gate and lifespan context.

`app/mcp_server/tools.py` (the `@mcp.tool()` wrappers) is intentionally thin -- each
one just pulls `AppContext` off the request and delegates to `domain.py`, which is
covered directly in `test_mcp_server.py`. A genuine live round trip through the MCP
protocol (real `ClientSession` + streamable-http transport) is exercised manually per
the architecture plan's verification section (connect from Claude Desktop / an MCP
inspector), and `app/mcp_server/tools.py` is covered by `[tool.coverage.run] omit`
alongside `server.py`/`__main__.py` for that reason.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.core.security import create_access_token
from app.mcp_server.auth import BearerAuthMiddleware, _bearer_token
from app.mcp_server.context import app_lifespan
from tests.conftest import TestSession, settings_for_tests


async def _echo(_request):
    return JSONResponse({"ok": True})


@asynccontextmanager
async def _guarded_client() -> AsyncIterator[AsyncClient]:
    """An httpx client over the auth middleware, in-process on the test event loop --
    mirrors `conftest.py`'s `client` fixture (`ASGITransport` + `AsyncClient`) rather than
    Starlette's synchronous `TestClient`, which drives the ASGI app on a separate thread
    that this project's `[tool.coverage.run] concurrency = ["greenlet"]` setting does not
    trace."""
    inner = Starlette(routes=[Route("/mcp", _echo), Route("/healthz", _echo)])
    guarded = BearerAuthMiddleware(inner, settings=settings_for_tests, session_factory=TestSession)
    transport = ASGITransport(app=guarded)
    async with AsyncClient(transport=transport, base_url="http://test") as guarded_client:
        yield guarded_client


class TestBearerTokenParsing:
    def test_missing_header_returns_none(self) -> None:
        assert _bearer_token({"headers": []}) is None

    def test_non_bearer_scheme_returns_none(self) -> None:
        headers = [(b"authorization", b"Basic dXNlcjpwYXNz")]
        assert _bearer_token({"headers": headers}) is None

    def test_empty_bearer_token_returns_none(self) -> None:
        headers = [(b"authorization", b"Bearer ")]
        assert _bearer_token({"headers": headers}) is None

    def test_valid_bearer_header_extracts_token(self) -> None:
        headers = [(b"authorization", b"Bearer abc.def.ghi")]
        assert _bearer_token({"headers": headers}) == "abc.def.ghi"


class TestBearerAuthMiddleware:
    async def test_healthz_is_exempt_without_a_token(self) -> None:
        async with _guarded_client() as guarded:
            response = await guarded.get("/healthz")
        assert response.status_code == 200

    async def test_missing_token_is_rejected(self) -> None:
        async with _guarded_client() as guarded:
            response = await guarded.get("/mcp")
        assert response.status_code == 401
        assert response.json()["code"] == "AUTH_REQUIRED"

    async def test_malformed_token_is_rejected(self) -> None:
        async with _guarded_client() as guarded:
            response = await guarded.get("/mcp", headers={"Authorization": "Bearer not-a-jwt"})
        assert response.status_code == 401
        assert response.json()["code"] == "INVALID_TOKEN"

    async def test_validly_signed_token_with_non_uuid_subject_is_rejected(self) -> None:
        token = create_access_token(
            subject="not-a-uuid", role="MANAGER", settings=settings_for_tests
        )
        async with _guarded_client() as guarded:
            response = await guarded.get("/mcp", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.json()["code"] == "INVALID_TOKEN"

    async def test_token_for_deleted_user_is_rejected(self) -> None:
        token = create_access_token(
            subject=str(uuid4()), role="MANAGER", settings=settings_for_tests
        )
        async with _guarded_client() as guarded:
            response = await guarded.get("/mcp", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.json()["code"] == "USER_NOT_FOUND"

    async def test_valid_manager_token_passes_through(self, client) -> None:
        login = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "gerencia@bmsc.com.bo",
                "password": settings_for_tests.seed_manager_password.get_secret_value(),
            },
        )
        assert login.status_code == 200, login.text
        access_token = login.json()["access_token"]

        async with _guarded_client() as guarded:
            response = await guarded.get(
                "/mcp", headers={"Authorization": f"Bearer {access_token}"}
            )
        assert response.status_code == 200
        assert response.json() == {"ok": True}


async def test_app_lifespan_yields_context_and_disposes() -> None:
    async with app_lifespan(None) as ctx:
        assert ctx.settings is settings_for_tests
        async with ctx.session_factory() as db:
            assert db.is_active
