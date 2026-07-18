from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import KioskSession, Requirement
from tests.conftest import TestSession


async def _session(client: AsyncClient) -> tuple[str, str]:
    response = await client.post("/api/v1/kiosk/sessions", json={})
    assert response.status_code == 201, response.text
    data = response.json()
    return data["session_id"], data["session_token"]


async def test_general_query_is_masked_and_resolved_automatically(client: AsyncClient) -> None:
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    transcript = "Mi correo es cliente@example.com y quiero conocer el horario de atencion"
    turn = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": transcript},
    )
    assert turn.status_code == 200, turn.text
    analysis = turn.json()
    assert analysis["next_action"] == "CONFIRM"
    assert analysis["category"] == "CONSULTA_GENERAL"
    assert "EMAIL" in analysis["pii_types"]

    confirmation = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json={"confirmed": True},
    )
    assert confirmation.status_code == 200, confirmation.text
    result = confirmation.json()
    assert result["resolution_type"] == "AUTOMATIC"
    assert result["grounding_status"] == "GROUNDED"
    assert result["citations"][0]["title"] == "Horarios de atención"
    assert result["ticket"]["status"] == "CERRADO"
    assert result["ticket"]["estimated_wait_minutes"] == 0
    assert result["response"]

    async with TestSession() as db:
        requirement = await db.scalar(select(Requirement))
        assert requirement is not None
        assert "cliente@example.com" not in requirement.masked_text
        assert "[EMAIL]" in requirement.masked_text


async def test_ambiguous_query_requests_clarification(client: AsyncClient) -> None:
    session_id, token = await _session(client)
    response = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers={"X-Session-Token": token},
        json={"turn_id": str(uuid4()), "transcript": "Necesito ayuda con algo"},
    )
    assert response.status_code == 200
    assert response.json()["next_action"] == "CLARIFY"


async def test_general_query_without_rag_evidence_is_routed_to_human(
    client: AsyncClient,
) -> None:
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    turn = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={
            "turn_id": str(uuid4()),
            "transcript": "Quiero información sobre un producto desconocido",
        },
    )
    assert turn.status_code == 200
    confirmation = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json={"confirmed": True},
    )
    assert confirmation.status_code == 200
    result = confirmation.json()
    assert result["resolution_type"] == "HUMAN"
    assert result["grounding_status"] == "NO_EVIDENCE"
    assert result["citations"] == []


async def test_session_token_is_required(client: AsyncClient) -> None:
    session_id, _ = await _session(client)
    response = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        json={"turn_id": str(uuid4()), "transcript": "horarios"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_TOKEN_REQUIRED"


async def test_expired_session_is_rejected(client: AsyncClient) -> None:
    session_id, token = await _session(client)
    async with TestSession() as db:
        session = await db.get(KioskSession, UUID(session_id))
        assert session is not None
        session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
    response = await client.get(
        f"/api/v1/kiosk/sessions/{session_id}",
        headers={"X-Session-Token": token},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_EXPIRED"


async def test_turn_state_machine_rejects_false_clarification_flag(
    client: AsyncClient,
) -> None:
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    ambiguous = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": "Necesito ayuda con algo"},
    )
    assert ambiguous.json()["next_action"] == "CLARIFY"
    mismatch = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={
            "turn_id": str(uuid4()),
            "transcript": "Es sobre una tarjeta",
            "is_clarification": False,
        },
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["code"] == "INVALID_CLARIFICATION"


async def test_duplicate_analysis_while_awaiting_confirmation_returns_pending_summary(
    client: AsyncClient,
) -> None:
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    first = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": "Quiero denunciar un fraude"},
    )
    assert first.status_code == 200

    repeated = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": "Quiero denunciar un fraude"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["requirement_id"] == first.json()["requirement_id"]
    assert repeated.json()["next_action"] == "CONFIRM"
