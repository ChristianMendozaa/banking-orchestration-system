from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import Requirement
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
