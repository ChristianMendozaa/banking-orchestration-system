from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import OperationalAuditEvent, Ticket
from app.domain.enums import Priority
from tests.conftest import TestSession, settings_for_tests


async def _login(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "gerencia@bmsc.com.bo",
            "password": settings_for_tests.seed_manager_password.get_secret_value(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _human_ticket(client: AsyncClient) -> str:
    created = await client.post("/api/v1/kiosk/sessions", json={})
    session_id = created.json()["session_id"]
    headers = {"X-Session-Token": created.json()["session_token"]}
    turn = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": "Tengo un movimiento no reconocido"},
    )
    confirmed = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json={"requirement_id": turn.json()["requirement_id"], "confirmed": True},
    )
    assert confirmed.json()["next_action"] == "IDENTIFY"
    identified = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/identification",
        headers=headers,
        json={"identifier": "6735666"},
    )
    assert identified.status_code == 200, identified.text
    return identified.json()["ticket"]["id"]


async def test_manager_assignment_priority_availability_and_audit(client: AsyncClient) -> None:
    ticket_id = await _human_ticket(client)
    async with TestSession() as db:
        ticket = await db.scalar(
            select(Ticket)
            .where(Ticket.public_id == UUID(ticket_id))
            .options(selectinload(Ticket.case))
        )
        assert ticket
        ticket.case.priority = Priority.MEDIO
        await db.commit()
    token = await _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    metrics = await client.get("/api/v1/management/metrics", headers=headers)
    available = next(
        executive
        for executive in metrics.json()["executives"]
        if executive["status"] == "DISPONIBLE"
    )

    raised = await client.patch(
        f"/api/v1/management/tickets/{ticket_id}/priority",
        headers=headers,
        json={
            "priority": "ALTO",
            "expected_version": 1,
            "reason": "La gerencia confirmó impacto inmediato para el cliente.",
        },
    )
    assert raised.status_code == 200, raised.text
    assert raised.json()["priority"] == "ALTO"
    assert raised.json()["version"] == 2

    unassigned = await client.patch(
        f"/api/v1/management/tickets/{ticket_id}/assignment",
        headers=headers,
        json={
            "executive_id": None,
            "expected_version": 2,
            "reason": "Redistribución manual para equilibrar la carga operativa.",
        },
    )
    assert unassigned.status_code == 200, unassigned.text
    assert unassigned.json()["executive_id"] is None
    assert unassigned.json()["version"] == 3

    queue = await client.get(
        "/api/v1/management/cases?unassigned=true",
        headers=headers,
    )
    assert any(item["id"] == ticket_id for item in queue.json()["items"])

    assigned = await client.patch(
        f"/api/v1/management/tickets/{ticket_id}/assignment",
        headers=headers,
        json={
            "executive_id": available["id"],
            "expected_version": 3,
            "reason": "Asignación gerencial al ejecutivo disponible seleccionado.",
        },
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["executive_id"] == available["id"]
    assert assigned.json()["version"] == 4

    conflict = await client.patch(
        f"/api/v1/management/tickets/{ticket_id}/assignment",
        headers=headers,
        json={
            "executive_id": None,
            "expected_version": 3,
            "reason": "Intento con una versión de datos que ya quedó desactualizada.",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "VERSION_CONFLICT"

    disabled = await client.patch(
        f"/api/v1/management/executives/{available['id']}/status",
        headers=headers,
        json={"status": "INACTIVO", "expected_version": available["version"]},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["unassigned_tickets"] >= 1

    async with TestSession() as db:
        ticket = await db.scalar(select(Ticket).where(Ticket.public_id == UUID(ticket_id)))
        assert ticket and ticket.executive_id is None
        actions = list(
            await db.scalars(
                select(OperationalAuditEvent.action).where(
                    OperationalAuditEvent.target_id.in_([ticket_id, available["id"]])
                )
            )
        )
    assert actions.count("TICKET_ASSIGNMENT_UPDATED") == 2
    assert "TICKET_PRIORITY_RAISED" in actions
    assert "EXECUTIVE_STATUS_UPDATED" in actions
