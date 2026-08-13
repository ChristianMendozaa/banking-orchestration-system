"""Pure domain logic backing the MCP tools.

Deliberately free of any MCP SDK import: every function here takes an `AsyncSession`
and plain arguments and returns a schema from `app.mcp_server.schemas`. The `@mcp.tool()`
wrappers in `tools.py` are thin adapters that pull these arguments out of MCP's request
context. Keeping the split means this module is testable exactly like the rest of the
codebase's services, without needing a live MCP client/server round trip.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.db.models import CaseRecord, Ticket, TraceEvent
from app.db.repositories import ExecutiveRepository
from app.domain.enums import Category
from app.knowledge.repository import KnowledgeRepository
from app.mcp_server.schemas import (
    CaseTraceResult,
    ExecutiveAvailabilityOut,
    ExecutiveSkillOut,
    KnowledgeSearchHit,
    KnowledgeSearchResult,
    RoutingCandidateOut,
    RoutingExplanationOut,
    TicketStatusResult,
    TraceEventOut,
)
from app.services.agents import DerivationAgent
from app.services.openai_provider import OpenAIProvider

_executive_repository = ExecutiveRepository()
_knowledge_repository = KnowledgeRepository()


async def search_knowledge(
    db: AsyncSession,
    provider: OpenAIProvider | None,
    query: str,
    category: Category,
    top_k: int,
    min_score: float,
) -> KnowledgeSearchResult:
    if not provider:
        raise AppError(
            "OPENAI_UNAVAILABLE",
            "El proveedor de embeddings no esta configurado",
            503,
        )
    query_embedding = await provider.embedding(query)
    chunks = await _knowledge_repository.retrieve(
        db,
        query_embedding=query_embedding,
        category=category,
        top_k=top_k,
        min_score=min_score,
    )
    hits = [
        KnowledgeSearchHit(
            chunk_id=item.chunk.id,
            document_id=item.document.id,
            title=item.document.title,
            section=item.chunk.section,
            page=item.chunk.page,
            source_url=item.document.source_urls[0] if item.document.source_urls else None,
            score=max(-1.0, min(1.0, item.score)),
            content=item.chunk.content,
        )
        for item in chunks
    ]
    return KnowledgeSearchResult(query=query, category=category, hits=hits)


async def get_case_trace(db: AsyncSession, case_id: UUID) -> CaseTraceResult:
    case = await db.get(CaseRecord, case_id)
    if not case:
        raise AppError("CASE_NOT_FOUND", "El caso no existe", 404)
    rows = (
        await db.scalars(
            select(TraceEvent).where(TraceEvent.case_id == case_id).order_by(TraceEvent.created_at)
        )
    ).all()
    return CaseTraceResult(
        case_id=case.id,
        category=case.category,
        priority=case.priority,
        identification_status=case.identification_status,
        status=case.status.value,
        events=[
            TraceEventOut(
                event_type=event.event_type,
                description=event.description,
                metadata=event.metadata_json,
                created_at=event.created_at,
            )
            for event in rows
        ],
    )


async def list_executive_availability(
    db: AsyncSession, category: Category | None
) -> list[ExecutiveAvailabilityOut]:
    executives = await _executive_repository.available(db)
    loads = await _executive_repository.active_loads(db)
    result = []
    for executive in executives:
        skills = executive.skills
        if category is not None:
            skills = [skill for skill in skills if skill.category == category]
            if not skills:
                continue
        result.append(
            ExecutiveAvailabilityOut(
                executive_id=executive.id,
                display_name=executive.display_name,
                title=executive.title,
                status=executive.status,
                active_load=loads[executive.id],
                skills=[
                    ExecutiveSkillOut(
                        category=skill.category, experience_level=skill.experience_level
                    )
                    for skill in skills
                ],
            )
        )
    return result


async def get_ticket_status(db: AsyncSession, ticket_public_id: UUID) -> TicketStatusResult:
    ticket = await db.scalar(
        select(Ticket)
        .where(Ticket.public_id == ticket_public_id)
        .options(selectinload(Ticket.case), selectinload(Ticket.executive))
    )
    if not ticket:
        raise AppError("TICKET_NOT_FOUND", "El ticket no existe", 404)
    return TicketStatusResult(
        ticket_id=ticket.public_id,
        number=ticket.number,
        status=ticket.status,
        automatic=ticket.automatic,
        priority=ticket.case.priority if ticket.case else None,
        estimated_wait_minutes=ticket.estimated_wait_minutes,
        executive_display_name=ticket.executive.display_name if ticket.executive else None,
        executive_window_number=ticket.executive.window_number if ticket.executive else None,
        created_at=ticket.created_at,
    )


async def explain_routing_decision(
    db: AsyncSession, provider: OpenAIProvider | None, case_id: UUID
) -> RoutingExplanationOut:
    case = await db.get(CaseRecord, case_id)
    if not case:
        raise AppError("CASE_NOT_FOUND", "El caso no existe", 404)
    derivation = DerivationAgent(provider, _executive_repository)
    ranked = await derivation.explain(db, case.category, case.summary)
    if not ranked:
        return RoutingExplanationOut(
            case_id=case.id,
            category=case.category,
            candidates=[],
            note="No hay ejecutivos disponibles con la categoria requerida",
        )
    candidates = [
        RoutingCandidateOut(
            executive_id=decision.executive.id,
            display_name=decision.executive.display_name,
            score=decision.score,
            semantic_score=decision.semantic_score,
            experience_score=decision.experience_score,
            load_score=decision.load_score,
            active_load=decision.active_load,
            selected=index == 0,
        )
        for index, decision in enumerate(ranked)
    ]
    note = (
        None if provider else "Ranking calculado sin proveedor de embeddings (score semantico=1.0)"
    )
    return RoutingExplanationOut(
        case_id=case.id, category=case.category, candidates=candidates, note=note
    )


__all__ = [
    "explain_routing_decision",
    "get_case_trace",
    "get_ticket_status",
    "list_executive_availability",
    "search_knowledge",
]
