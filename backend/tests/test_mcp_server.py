from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.core.security import hash_token
from app.db.models import CaseRecord, KioskSession, Requirement, Ticket
from app.domain.enums import (
    CaseStatus,
    Category,
    ConsultationLevel,
    IdentificationStatus,
    Priority,
    SessionStatus,
    TicketStatus,
)
from app.mcp_server import domain
from app.services.agents import DerivationAgent, PrioritizationAgent
from tests.conftest import TestSession, fake_provider


async def _seed_case(category: Category = Category.REPORTE_FRAUDE) -> CaseRecord:
    """Build a minimal session -> requirement -> case chain, mirroring what
    `OrchestratorService.confirm` produces, so the read-only MCP tools have
    case-shaped data to report on."""
    async with TestSession() as db:
        session = KioskSession(
            access_token_hash=hash_token(f"tok-{uuid4()}"),
            status=SessionStatus.ORCHESTRATING,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        db.add(session)
        await db.flush()

        requirement = Requirement(
            session_id=session.id,
            turn_id=uuid4(),
            masked_text="Movimiento no reconocido en mi tarjeta",
            summary="Reporte de movimiento no reconocido",
            customer_summary="Necesitas reportar un posible fraude.",
            category=category,
            proposed_priority=Priority.CRITICO,
            consultation_level=ConsultationLevel.SENSIBLE,
            confidence=0.9,
            classification_source="FALLBACK",
        )
        db.add(requirement)
        await db.flush()

        case = CaseRecord(
            session_id=session.id,
            requirement_id=requirement.id,
            category=category,
            priority=Priority.CRITICO,
            consultation_level=ConsultationLevel.SENSIBLE,
            identification_status=IdentificationStatus.IDENTIFICADO,
            summary=requirement.summary,
            status=CaseStatus.CLASSIFIED,
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)
        return case


class TestSearchKnowledge:
    async def test_requires_provider(self) -> None:
        async with TestSession() as db:
            with pytest.raises(AppError) as excinfo:
                await domain.search_knowledge(
                    db, None, "horarios", Category.CONSULTA_GENERAL, 5, 0.45
                )
        assert excinfo.value.code == "OPENAI_UNAVAILABLE"

    async def test_returns_seeded_chunk_with_fake_provider(self) -> None:
        async with TestSession() as db:
            result = await domain.search_knowledge(
                db, fake_provider, "horario", Category.CONSULTA_GENERAL, 5, 0.1
            )
        assert result.category == Category.CONSULTA_GENERAL
        assert len(result.hits) == 1
        assert "línea gratuita" in result.hits[0].content


class TestCaseTrace:
    async def test_unknown_case_raises(self) -> None:
        async with TestSession() as db:
            with pytest.raises(AppError) as excinfo:
                await domain.get_case_trace(db, uuid4())
        assert excinfo.value.code == "CASE_NOT_FOUND"

    async def test_trace_reflects_case_state(self) -> None:
        case = await _seed_case()
        async with TestSession() as db:
            result = await domain.get_case_trace(db, case.id)
        assert result.category == Category.REPORTE_FRAUDE
        assert result.priority == Priority.CRITICO
        assert result.identification_status == IdentificationStatus.IDENTIFICADO


class TestExecutiveAvailability:
    async def test_lists_seeded_executives(self) -> None:
        async with TestSession() as db:
            result = await domain.list_executive_availability(db, None)
        assert len(result) >= 1
        assert all(row.active_load == 0 for row in result)

    async def test_filters_by_category(self) -> None:
        async with TestSession() as db:
            result = await domain.list_executive_availability(db, Category.BANCA_DIGITAL)
        assert result
        assert all(
            any(skill.category == Category.BANCA_DIGITAL for skill in row.skills) for row in result
        )


class TestTicketStatus:
    async def test_unknown_ticket_raises(self) -> None:
        async with TestSession() as db:
            with pytest.raises(AppError) as excinfo:
                await domain.get_ticket_status(db, uuid4())
        assert excinfo.value.code == "TICKET_NOT_FOUND"

    async def test_returns_ticket_shape(self) -> None:
        case = await _seed_case()
        async with TestSession() as db:
            ticket = Ticket(
                public_id=uuid4(),
                case_id=case.id,
                automatic=False,
                status=TicketStatus.PENDIENTE,
                estimated_wait_minutes=8,
            )
            db.add(ticket)
            await db.commit()
            public_id = ticket.public_id

        async with TestSession() as db:
            result = await domain.get_ticket_status(db, public_id)
        assert result.status == TicketStatus.PENDIENTE
        assert result.priority == Priority.CRITICO
        assert result.estimated_wait_minutes == 8
        assert result.executive_display_name is None


class TestExplainRoutingDecision:
    async def test_unknown_case_raises(self) -> None:
        async with TestSession() as db:
            with pytest.raises(AppError) as excinfo:
                await domain.explain_routing_decision(db, None, uuid4())
        assert excinfo.value.code == "CASE_NOT_FOUND"

    async def test_ranks_available_executives_without_provider(self) -> None:
        case = await _seed_case(category=Category.REPORTE_FRAUDE)
        async with TestSession() as db:
            result = await domain.explain_routing_decision(db, None, case.id)
        assert result.category == Category.REPORTE_FRAUDE
        assert result.candidates, "seeded executives include REPORTE_FRAUDE skill coverage"
        assert result.candidates[0].selected is True
        assert result.note is not None
        assert sum(1 for candidate in result.candidates if candidate.selected) == 1
        scores = [candidate.score for candidate in result.candidates]
        assert scores == sorted(scores, reverse=True)

    async def test_no_available_executives_returns_empty_with_note(self) -> None:
        from sqlalchemy import update

        from app.db.models import Executive
        from app.domain.enums import ExecutiveStatus

        case = await _seed_case(category=Category.REPORTE_FRAUDE)
        async with TestSession() as db:
            await db.execute(update(Executive).values(status=ExecutiveStatus.INACTIVO))
            await db.commit()

        async with TestSession() as db:
            result = await domain.explain_routing_decision(db, None, case.id)
        assert result.candidates == []
        assert result.note == "No hay ejecutivos disponibles con la categoria requerida"


async def test_derivation_agent_explain_matches_run() -> None:
    """`explain()` must never change what `run()` would have picked."""
    async with TestSession() as db:
        derivation = DerivationAgent(provider=None)
        winner = await derivation.run(db, Category.BANCA_DIGITAL, "acceso a banca digital")
        ranked = await derivation.explain(db, Category.BANCA_DIGITAL, "acceso a banca digital")
        assert winner is not None
        assert ranked[0].executive.id == winner.executive.id


def test_prioritization_agent_still_pure() -> None:
    """Guard against Phase 1 accidentally coupling prioritization to the MCP layer."""
    agent = PrioritizationAgent()
    assert agent.run(Category.REPORTE_FRAUDE, "fraude", False) == Priority.CRITICO
