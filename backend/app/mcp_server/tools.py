"""Tool registration: thin adapters between MCP's request context and `domain.py`.

Each wrapper pulls the lifespan-scoped `AppContext` off `ctx.request_context.lifespan_context`,
opens a session for the duration of the call, and delegates to a pure function in
`domain.py`. No business logic lives here.
"""

from uuid import UUID

from mcp.server.mcpserver import Context, MCPServer

from app.domain.enums import Category
from app.mcp_server import domain
from app.mcp_server.context import AppContext
from app.mcp_server.schemas import (
    CaseTraceResult,
    ExecutiveAvailabilityOut,
    KnowledgeSearchResult,
    RoutingExplanationOut,
    TicketStatusResult,
)


def _app_context(ctx: Context) -> AppContext:
    return ctx.request_context.lifespan_context


def register_tools(mcp: MCPServer) -> None:
    @mcp.tool(
        description=(
            "Busca en la base de conocimiento gobernada (documentos PDF versionados, "
            "indexados con pgvector) evidencia relevante para una consulta bancaria, "
            "acotada a una categoria. Devuelve fragmentos con su cita (documento, pagina, "
            "puntaje de similitud); no genera una respuesta, solo recupera evidencia."
        )
    )
    async def search_knowledge(
        query: str,
        category: Category,
        ctx: Context,
        top_k: int = 5,
        min_score: float = 0.45,
    ) -> KnowledgeSearchResult:
        app_ctx = _app_context(ctx)
        async with app_ctx.session_factory() as db:
            return await domain.search_knowledge(
                db, app_ctx.provider, query, category, top_k, min_score
            )

    @mcp.tool(
        description=(
            "Devuelve la linea de tiempo auditable de un caso (TraceEvent): enmascarado de "
            "PII, clasificacion, prioridad asignada, ruteo y resultado. No incluye datos "
            "personales sin enmascarar ni identificadores revelados."
        )
    )
    async def get_case_trace(case_id: UUID, ctx: Context) -> CaseTraceResult:
        app_ctx = _app_context(ctx)
        async with app_ctx.session_factory() as db:
            return await domain.get_case_trace(db, case_id)

    @mcp.tool(
        description=(
            "Lista ejecutivos disponibles, su carga activa (tickets pendientes o en "
            "atencion) y sus habilidades por categoria. Util para entender capacidad "
            "operativa antes de derivar un caso."
        )
    )
    async def list_executive_availability(
        ctx: Context, category: Category | None = None
    ) -> list[ExecutiveAvailabilityOut]:
        app_ctx = _app_context(ctx)
        async with app_ctx.session_factory() as db:
            return await domain.list_executive_availability(db, category)

    @mcp.tool(
        description=(
            "Consulta el estado de un ticket (pendiente, en atencion, cerrado), su "
            "prioridad, espera estimada y ejecutivo asignado. No revela el identificador "
            "del cliente: eso requiere el flujo de revelado exclusivo del ejecutivo asignado."
        )
    )
    async def get_ticket_status(ticket_public_id: UUID, ctx: Context) -> TicketStatusResult:
        app_ctx = _app_context(ctx)
        async with app_ctx.session_factory() as db:
            return await domain.get_ticket_status(db, ticket_public_id)

    @mcp.tool(
        description=(
            "Explica por que un caso fue (o seria) derivado a un ejecutivo: recalcula el "
            "ranking completo de DerivationAgent (70% semantico, 20% experiencia, 10% carga) "
            "sobre los ejecutivos disponibles, sin modificar la asignacion real del caso."
        )
    )
    async def explain_routing_decision(case_id: UUID, ctx: Context) -> RoutingExplanationOut:
        app_ctx = _app_context(ctx)
        async with app_ctx.session_factory() as db:
            return await domain.explain_routing_decision(db, app_ctx.provider, case_id)
