"""Builds the MCP server and wraps it with bearer-token auth."""

from mcp.server.mcpserver import MCPServer
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.mcp_server.auth import BearerAuthMiddleware
from app.mcp_server.context import app_lifespan
from app.mcp_server.tools import register_tools

INSTRUCTIONS = (
    "Herramientas de solo lectura sobre el dominio de orquestacion de atencion bancaria: "
    "busqueda en la base de conocimiento gobernada, trazabilidad auditable de casos, "
    "disponibilidad y carga de ejecutivos, estado de tickets, y explicacion del ranking de "
    "derivacion. Este servidor nunca expone mutacion de sesiones de kiosco ni revelado de "
    "identificadores de cliente; esas operaciones permanecen exclusivas de la API REST "
    "autenticada por rol."
)


def build_server() -> MCPServer:
    mcp = MCPServer(
        name="sistema-orquestacion-domain",
        title="Dominio de orquestacion bancaria",
        instructions=INSTRUCTIONS,
        lifespan=app_lifespan,
    )
    register_tools(mcp)

    @mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def healthz(_request):  # noqa: ANN001, ANN202
        return JSONResponse({"status": "ok"})

    return mcp


def create_app() -> ASGIApp:
    mcp = build_server()
    inner: Starlette = mcp.streamable_http_app()
    settings = get_settings()
    return BearerAuthMiddleware(inner, settings=settings, session_factory=SessionFactory)
