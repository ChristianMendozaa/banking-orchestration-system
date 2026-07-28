from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import ConversationMessage, Identification, KioskSession, Ticket
from app.domain.enums import ConversationRole, SessionStatus
from app.services.retention import purge_expired_conversations
from tests.conftest import TestSession, settings_for_tests


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _fraud_ticket(client: AsyncClient) -> dict:
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
    return {"session_id": session_id, "headers": headers, "result": identified.json()}


def _executive_email(name: str) -> str:
    return {
        "Carlos Mamani": "carlos.mamani@bmsc.com.bo",
        "Maria Fernandez": "maria.fernandez@bmsc.com.bo",
    }[name]


async def test_conversation_and_identifier_are_exposed_by_role(client: AsyncClient) -> None:
    flow = await _fraud_ticket(client)
    synced = await client.post(
        f"/api/v1/kiosk/sessions/{flow['session_id']}/conversation/messages",
        headers=flow["headers"],
        json={
            "messages": [
                {
                    "item_id": "customer-1",
                    "role": "CUSTOMER",
                    "text": "Mi correo es ana@example.com y necesito ayuda",
                },
                {
                    "item_id": "assistant-1",
                    "role": "ASSISTANT",
                    "text": "Te ayudaré sin repetir ana@example.com",
                },
            ]
        },
    )
    assert synced.status_code == 200
    assert synced.json()["accepted"] == 2
    repeated = await client.post(
        f"/api/v1/kiosk/sessions/{flow['session_id']}/conversation/messages",
        headers=flow["headers"],
        json={"messages": [{"item_id": "customer-1", "role": "CUSTOMER", "text": "otro"}]},
    )
    assert repeated.json()["accepted"] == 0

    executive_token = await _login(
        client,
        _executive_email(flow["result"]["executive"]["name"]),
        settings_for_tests.seed_executive_password.get_secret_value(),
    )
    ticket_id = flow["result"]["ticket"]["id"]
    detail = await client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {executive_token}"},
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["identity"]["display_name"] == "Christian Mendoza"
    assert body["identity"]["masked_identifier"] == "****5666"
    assert body["identity"]["reveal_available"] is True
    assert len(body["conversation"]) == 2
    assert all("ana@example.com" not in message["text"] for message in body["conversation"])

    started = await client.patch(
        f"/api/v1/tickets/{ticket_id}/status",
        headers={"Authorization": f"Bearer {executive_token}"},
        json={"status": "EN_ATENCION", "expected_version": 1},
    )
    assert started.status_code == 200, started.text
    revealed = await client.post(
        f"/api/v1/tickets/{ticket_id}/identifier/reveal",
        headers={"Authorization": f"Bearer {executive_token}"},
    )
    assert revealed.status_code == 200, revealed.text
    assert revealed.json()["identifier"] == "6735666"
    assert revealed.headers["cache-control"].startswith("no-store")

    manager_token = await _login(
        client,
        "gerencia@bmsc.com.bo",
        settings_for_tests.seed_manager_password.get_secret_value(),
    )
    manager_detail = await client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert manager_detail.status_code == 200
    assert manager_detail.json()["identity"]["display_name"] is None
    assert manager_detail.json()["identity"]["reveal_available"] is False
    forbidden = await client.post(
        f"/api/v1/tickets/{ticket_id}/identifier/reveal",
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert forbidden.status_code == 403


async def test_single_active_case_and_documented_close(client: AsyncClient) -> None:
    first = await _fraud_ticket(client)
    second = await _fraud_ticket(client)
    first_id = UUID(first["result"]["ticket"]["id"])
    second_id = UUID(second["result"]["ticket"]["id"])
    async with TestSession() as db:
        first_ticket = await db.scalar(select(Ticket).where(Ticket.public_id == first_id))
        second_ticket = await db.scalar(select(Ticket).where(Ticket.public_id == second_id))
        assert first_ticket and second_ticket
        second_ticket.executive_id = first_ticket.executive_id
        await db.commit()

    token = await _login(
        client,
        _executive_email(first["result"]["executive"]["name"]),
        settings_for_tests.seed_executive_password.get_secret_value(),
    )
    headers = {"Authorization": f"Bearer {token}"}
    started = await client.patch(
        f"/api/v1/tickets/{first_id}/status",
        headers=headers,
        json={"status": "EN_ATENCION", "expected_version": 1},
    )
    assert started.status_code == 200, started.text

    blocked = await client.patch(
        f"/api/v1/tickets/{second_id}/status",
        headers=headers,
        json={"status": "EN_ATENCION", "expected_version": 1},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "EXECUTIVE_ALREADY_ATTENDING"

    incomplete = await client.patch(
        f"/api/v1/tickets/{first_id}/status",
        headers=headers,
        json={"status": "CERRADO", "expected_version": 2},
    )
    assert incomplete.status_code == 422
    assert incomplete.json()["code"] == "RESOLUTION_REQUIRED"

    closed = await client.patch(
        f"/api/v1/tickets/{first_id}/status",
        headers=headers,
        json={
            "status": "CERRADO",
            "expected_version": 2,
            "resolution_outcome": "RESUELTO",
            "resolution_note": "Se atendió al cliente y se notificó a ana@example.com.",
        },
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["resolution_outcome"] == "RESUELTO"
    assert "ana@example.com" not in closed.json()["resolution_note"]
    async with TestSession() as db:
        identification = await db.scalar(
            select(Identification).where(Identification.case_id == first_ticket.case_id)
        )
        assert identification
        assert identification.identifier_ciphertext is None
        assert identification.identifier_nonce is None
        assert identification.identifier_key_id is None

    next_started = await client.patch(
        f"/api/v1/tickets/{second_id}/status",
        headers=headers,
        json={"status": "EN_ATENCION", "expected_version": 1},
    )
    assert next_started.status_code == 200, next_started.text
    listing = await client.get("/api/v1/executive/tickets", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["status_counts"]["EN_ATENCION"] == 1


async def test_expired_conversation_messages_are_purged() -> None:
    async with TestSession() as db:
        session = KioskSession(
            access_token_hash="retention-test-token",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            status=SessionStatus.LISTENING,
        )
        db.add(session)
        await db.flush()
        message = ConversationMessage(
            session_id=session.id,
            external_item_id="expired",
            role=ConversationRole.CUSTOMER,
            masked_text="Mensaje vencido",
        )
        message.created_at = datetime.now(UTC) - timedelta(days=91)
        db.add(message)
        await db.commit()
    deleted = await purge_expired_conversations(settings_for_tests, TestSession)
    assert deleted == 1
