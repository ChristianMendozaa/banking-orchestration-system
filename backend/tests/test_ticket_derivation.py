from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import Executive, Ticket
from app.domain.enums import CaseStatus, ExecutiveStatus, TicketStatus
from tests.conftest import TestSession, settings_for_tests
from tests.test_staff_operational_ux import _executive_email, _fraud_ticket, _login

pytestmark = [pytest.mark.functional, pytest.mark.integration, pytest.mark.regression]

FRAUD_EXECUTIVES = {"Carlos Mamani", "Maria Fernandez"}
NOTE = "El cliente necesita revisar un contrato; avisar a ana@example.com."


async def _owner_headers(client: AsyncClient, flow: dict) -> dict[str, str]:
    token = await _login(
        client,
        _executive_email(flow["result"]["executive"]["name"]),
        settings_for_tests.seed_executive_password.get_secret_value(),
    )
    return {"Authorization": f"Bearer {token}"}


async def _executive_ids() -> dict[str, UUID]:
    async with TestSession() as db:
        executives = (await db.scalars(select(Executive))).all()
        return {executive.display_name: executive.id for executive in executives}


async def _set_status(name: str, status: ExecutiveStatus) -> None:
    async with TestSession() as db:
        executive = await db.scalar(select(Executive).where(Executive.display_name == name))
        assert executive
        executive.status = status
        await db.commit()


async def test_automatic_derivation_hands_the_active_case_to_another_executive(
    client: AsyncClient,
) -> None:
    flow = await _fraud_ticket(client)
    owner = flow["result"]["executive"]["name"]
    ticket_id = flow["result"]["ticket"]["id"]
    headers = await _owner_headers(client, flow)
    started = await client.patch(
        f"/api/v1/tickets/{ticket_id}/status",
        headers=headers,
        json={"status": "EN_ATENCION", "expected_version": 1},
    )
    assert started.status_code == 200, started.text

    derived = await client.post(
        f"/api/v1/tickets/{ticket_id}/derivation",
        headers=headers,
        json={"expected_version": 2, "note": NOTE},
    )
    assert derived.status_code == 200, derived.text
    body = derived.json()
    (receiver,) = FRAUD_EXECUTIVES - {owner}
    assert body["automatic"] is True
    assert body["status"] == "PENDIENTE"
    assert body["executive_name"] == receiver
    assert body["window_number"]
    assert body["estimated_wait_minutes"] == settings_for_tests.estimated_service_minutes

    # The case left the executive who derived it, and they are free to take the next one.
    released = await client.get(f"/api/v1/tickets/{ticket_id}", headers=headers)
    assert released.status_code == 403
    async with TestSession() as db:
        previous = await db.scalar(select(Executive).where(Executive.display_name == owner))
        assert previous and previous.status == ExecutiveStatus.DISPONIBLE

    receiver_token = await _login(
        client,
        _executive_email(receiver),
        settings_for_tests.seed_executive_password.get_secret_value(),
    )
    receiver_headers = {"Authorization": f"Bearer {receiver_token}"}
    detail = await client.get(f"/api/v1/tickets/{ticket_id}", headers=receiver_headers)
    assert detail.status_code == 200, detail.text
    received = detail.json()
    assert received["status"] == "PENDIENTE"
    assert received["started_at"] is None
    assert received["resolution_outcome"] is None
    assert received["version"] == 3
    handoff = [event for event in received["events"] if event["event_type"] == "TICKET_DERIVED"]
    assert len(handoff) == 1
    assert f"de {owner} a {receiver}" in handoff[0]["description"]
    assert "Motivo:" in handoff[0]["description"]
    assert "ana@example.com" not in handoff[0]["description"]
    assert handoff[0]["metadata"]["mode"] == "AUTOMATIC"

    # A derivation is not a close: the identifier is still recoverable by whoever attends.
    assert received["identity"]["reveal_available"] is True
    resumed = await client.patch(
        f"/api/v1/tickets/{ticket_id}/status",
        headers=receiver_headers,
        json={"status": "EN_ATENCION", "expected_version": 3},
    )
    assert resumed.status_code == 200, resumed.text
    revealed = await client.post(
        f"/api/v1/tickets/{ticket_id}/identifier/reveal", headers=receiver_headers
    )
    assert revealed.status_code == 200, revealed.text
    assert revealed.json()["identifier"] == "6735666"


async def test_manual_derivation_queues_behind_a_busy_colleague(client: AsyncClient) -> None:
    flow = await _fraud_ticket(client)
    owner = flow["result"]["executive"]["name"]
    ticket_id = flow["result"]["ticket"]["id"]
    headers = await _owner_headers(client, flow)
    ids = await _executive_ids()
    await _set_status("Patricia Quispe", ExecutiveStatus.OCUPADO)
    await _set_status("Roberto Torrez", ExecutiveStatus.INACTIVO)

    # The backend rule the case page now respects: no full identifier before attention starts.
    early_reveal = await client.post(
        f"/api/v1/tickets/{ticket_id}/identifier/reveal", headers=headers
    )
    assert early_reveal.status_code == 409
    assert early_reveal.json()["code"] == "IDENTIFIER_REVEAL_NOT_ALLOWED"

    candidates = await client.get(
        f"/api/v1/tickets/{ticket_id}/derivation/candidates", headers=headers
    )
    assert candidates.status_code == 200, candidates.text
    by_name = {item["name"]: item for item in candidates.json()["items"]}
    assert owner not in by_name
    assert "Roberto Torrez" not in by_name
    assert by_name["Patricia Quispe"]["status"] == "OCUPADO"
    assert by_name["Patricia Quispe"]["active_load"] == 0

    async def derive(executive_id: UUID, version: int = 1):
        return await client.post(
            f"/api/v1/tickets/{ticket_id}/derivation",
            headers=headers,
            json={"expected_version": version, "note": NOTE, "executive_id": str(executive_id)},
        )

    stale = await derive(ids["Patricia Quispe"], version=7)
    assert (stale.status_code, stale.json()["code"]) == (409, "VERSION_CONFLICT")
    to_self = await derive(ids[owner])
    assert (to_self.status_code, to_self.json()["code"]) == (422, "DERIVATION_TARGET_INVALID")
    inactive = await derive(ids["Roberto Torrez"])
    assert (inactive.status_code, inactive.json()["code"]) == (409, "EXECUTIVE_NOT_AVAILABLE")
    unknown = await derive(uuid4())
    assert (unknown.status_code, unknown.json()["code"]) == (404, "EXECUTIVE_NOT_FOUND")

    derived = await derive(ids["Patricia Quispe"])
    assert derived.status_code == 200, derived.text
    body = derived.json()
    assert body["automatic"] is False
    assert body["executive_name"] == "Patricia Quispe"
    assert body["window_number"] == "Ventanilla 5"
    async with TestSession() as db:
        ticket = await db.scalar(
            select(Ticket)
            .where(Ticket.public_id == UUID(ticket_id))
            .options(selectinload(Ticket.case), selectinload(Ticket.executive))
        )
        assert ticket and ticket.executive
        assert ticket.executive_id == ids["Patricia Quispe"]
        assert ticket.status == TicketStatus.PENDIENTE
        assert ticket.case.status == CaseStatus.ASSIGNED
        # Receiving a case does not interrupt the attention already in progress.
        assert ticket.executive.status == ExecutiveStatus.OCUPADO


async def test_derivation_without_a_receiver_returns_the_case_to_the_open_queue(
    client: AsyncClient,
) -> None:
    flow = await _fraud_ticket(client)
    owner = flow["result"]["executive"]["name"]
    ticket_id = flow["result"]["ticket"]["id"]
    headers = await _owner_headers(client, flow)
    for name in await _executive_ids():
        if name != owner:
            await _set_status(name, ExecutiveStatus.INACTIVO)

    derived = await client.post(
        f"/api/v1/tickets/{ticket_id}/derivation",
        headers=headers,
        json={"expected_version": 1, "note": NOTE},
    )
    assert derived.status_code == 200, derived.text
    body = derived.json()
    assert body["executive_id"] is None
    assert body["executive_name"] is None
    assert body["estimated_wait_minutes"] is None
    async with TestSession() as db:
        ticket = await db.scalar(
            select(Ticket)
            .where(Ticket.public_id == UUID(ticket_id))
            .options(selectinload(Ticket.case))
        )
        assert ticket
        assert ticket.executive_id is None
        assert ticket.assigned_at is None
        assert ticket.status == TicketStatus.PENDIENTE
        assert ticket.case.status == CaseStatus.QUEUED


async def test_derived_is_no_longer_a_way_to_close_and_closed_cases_stay_closed(
    client: AsyncClient,
) -> None:
    flow = await _fraud_ticket(client)
    ticket_id = flow["result"]["ticket"]["id"]
    headers = await _owner_headers(client, flow)
    started = await client.patch(
        f"/api/v1/tickets/{ticket_id}/status",
        headers=headers,
        json={"status": "EN_ATENCION", "expected_version": 1},
    )
    assert started.status_code == 200, started.text

    labelled = await client.patch(
        f"/api/v1/tickets/{ticket_id}/status",
        headers=headers,
        json={
            "status": "CERRADO",
            "expected_version": 2,
            "resolution_outcome": "DERIVADO",
            "resolution_note": "Se deriva el caso a otra ventanilla.",
        },
    )
    assert (labelled.status_code, labelled.json()["code"]) == (422, "DERIVATION_REQUIRED")

    closed = await client.patch(
        f"/api/v1/tickets/{ticket_id}/status",
        headers=headers,
        json={
            "status": "CERRADO",
            "expected_version": 2,
            "resolution_outcome": "RESUELTO",
            "resolution_note": "Se atendió al cliente en ventanilla.",
        },
    )
    assert closed.status_code == 200, closed.text
    late = await client.post(
        f"/api/v1/tickets/{ticket_id}/derivation",
        headers=headers,
        json={"expected_version": 3, "note": NOTE},
    )
    assert (late.status_code, late.json()["code"]) == (409, "INVALID_STATUS_TRANSITION")
