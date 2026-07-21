from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import CaseRecord, Identification, KioskSession, Requirement, Ticket
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
        json={"requirement_id": analysis["requirement_id"], "confirmed": True},
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
    headers = {"X-Session-Token": token}
    response = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": "Necesito ayuda con algo"},
    )
    assert response.status_code == 200
    assert response.json()["next_action"] == "CLARIFY"
    snapshot = await client.get(
        f"/api/v1/kiosk/sessions/{session_id}",
        headers=headers,
    )
    assert snapshot.status_code == 200
    assert snapshot.json()["analysis"] == response.json()


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
    analysis = turn.json()
    confirmation = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json={"requirement_id": analysis["requirement_id"], "confirmed": True},
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


async def test_completed_turn_retry_cannot_restore_confirmation(
    client: AsyncClient,
) -> None:
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    turn_id = str(uuid4())
    turn = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": turn_id, "transcript": "Tengo una compra no reconocida"},
    )
    assert turn.status_code == 200, turn.text
    confirmation = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json={"requirement_id": turn.json()["requirement_id"], "confirmed": True},
    )
    assert confirmation.status_code == 200, confirmation.text

    stale_turn = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": turn_id, "transcript": "Tengo una compra no reconocida"},
    )
    assert stale_turn.status_code == 409
    assert stale_turn.json()["code"] == "TURN_ALREADY_COMPLETED"


async def test_customer_summary_is_natural_and_confirmation_snapshot_is_recoverable(
    client: AsyncClient,
) -> None:
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    turn = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": "Necesito denunciar un fraude"},
    )
    assert turn.status_code == 200, turn.text
    analysis = turn.json()
    assert analysis["customer_summary"].startswith("Necesitas")
    assert analysis["speech_text"].startswith("¿Me confirmas si necesitas")
    assert "usuario" not in analysis["speech_text"].lower()
    assert "cliente" not in analysis["speech_text"].lower()

    snapshot = await client.get(
        f"/api/v1/kiosk/sessions/{session_id}",
        headers=headers,
    )
    assert snapshot.status_code == 200, snapshot.text
    body = snapshot.json()
    assert body["analysis"]["requirement_id"] == analysis["requirement_id"]
    assert body["analysis"]["speech_text"] == analysis["speech_text"]
    assert body["result"] is None

    async with TestSession() as db:
        requirement = await db.get(Requirement, UUID(analysis["requirement_id"]))
        assert requirement is not None
        assert requirement.customer_summary == analysis["customer_summary"]
        assert requirement.confirmation_decision is None


async def test_confirmation_and_identification_retries_return_one_ticket(
    client: AsyncClient,
) -> None:
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    turn = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": "Tengo una compra no reconocida"},
    )
    requirement_id = turn.json()["requirement_id"]
    confirmation_payload = {"requirement_id": requirement_id, "confirmed": True}

    first_confirmation = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json=confirmation_payload,
    )
    repeated_confirmation = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json=confirmation_payload,
    )
    assert first_confirmation.status_code == 200, first_confirmation.text
    assert repeated_confirmation.status_code == 200, repeated_confirmation.text
    assert first_confirmation.json() == repeated_confirmation.json()
    assert first_confirmation.json()["requirement_id"] == requirement_id
    assert first_confirmation.json()["next_action"] == "IDENTIFY"
    assert "desped" not in first_confirmation.json()["speech_text"].lower()

    identification_snapshot = await client.get(
        f"/api/v1/kiosk/sessions/{session_id}",
        headers=headers,
    )
    assert identification_snapshot.status_code == 200
    assert identification_snapshot.json()["analysis"] is None
    assert identification_snapshot.json()["result"] == first_confirmation.json()

    first_identification = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/identification",
        headers=headers,
        json={"identifier": "6735666"},
    )
    repeated_identification = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/identification",
        headers=headers,
        json={"identifier": "6735666"},
    )
    assert first_identification.status_code == 200, first_identification.text
    assert repeated_identification.status_code == 200, repeated_identification.text
    assert repeated_identification.json() == first_identification.json()
    assert first_identification.json()["requirement_id"] == requirement_id

    terminal_snapshot = await client.get(
        f"/api/v1/kiosk/sessions/{session_id}",
        headers=headers,
    )
    assert terminal_snapshot.status_code == 200
    assert terminal_snapshot.json()["result"] == first_identification.json()
    assert terminal_snapshot.json()["analysis"] is None
    assert terminal_snapshot.json()["result"]["customer_summary"].startswith("Necesitas")
    assert terminal_snapshot.json()["result"]["priority"] == "CRITICO"

    async with TestSession() as db:
        cases = list(await db.scalars(select(CaseRecord)))
        identifications = list(await db.scalars(select(Identification)))
        tickets = list(await db.scalars(select(Ticket)))
        requirement = await db.get(Requirement, UUID(requirement_id))
        assert len(cases) == len(identifications) == len(tickets) == 1
        assert requirement is not None
        assert requirement.confirmation_decision is True


async def test_negative_confirmation_retry_only_records_one_correction(
    client: AsyncClient,
) -> None:
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    turn = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": "Quiero denunciar un fraude"},
    )
    requirement_id = turn.json()["requirement_id"]
    payload = {"requirement_id": requirement_id, "confirmed": False}

    first = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json=payload,
    )
    repeated = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json=payload,
    )
    assert first.status_code == 200, first.text
    assert repeated.status_code == 200, repeated.text
    assert first.json() == repeated.json()
    assert first.json()["next_action"] == "CAPTURE"
    assert first.json()["speech_text"] == "Cuéntame nuevamente qué necesitas."
    conflicting = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json={"requirement_id": requirement_id, "confirmed": True},
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["code"] == "CONFIRMATION_ALREADY_RECORDED"

    async with TestSession() as db:
        kiosk_session = await db.get(KioskSession, UUID(session_id))
        requirement = await db.get(Requirement, UUID(requirement_id))
        assert kiosk_session is not None
        assert kiosk_session.correction_count == 1
        assert requirement is not None
        assert requirement.active is False
        assert requirement.confirmation_decision is False


async def test_stale_negative_confirmation_cannot_replace_a_new_requirement(
    client: AsyncClient,
) -> None:
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    first_turn = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": "Quiero denunciar un fraude"},
    )
    first_requirement_id = first_turn.json()["requirement_id"]
    rejection = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json={"requirement_id": first_requirement_id, "confirmed": False},
    )
    assert rejection.status_code == 200, rejection.text

    second_turn = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": "Necesito bloquear mi tarjeta"},
    )
    assert second_turn.status_code == 200, second_turn.text
    second_requirement_id = second_turn.json()["requirement_id"]
    assert second_requirement_id != first_requirement_id

    stale_retry = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json={"requirement_id": first_requirement_id, "confirmed": False},
    )
    assert stale_retry.status_code == 409
    assert stale_retry.json()["code"] == "REQUIREMENT_MISMATCH"

    snapshot = await client.get(
        f"/api/v1/kiosk/sessions/{session_id}",
        headers=headers,
    )
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["status"] == "AWAITING_CONFIRMATION"
    assert snapshot.json()["analysis"]["requirement_id"] == second_requirement_id


async def test_negative_confirmation_after_clarification_remains_idempotent(
    client: AsyncClient,
) -> None:
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    first = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": "Necesito ayuda con algo"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["next_action"] == "CLARIFY"

    clarified = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={
            "turn_id": str(uuid4()),
            "transcript": "Es por una compra que no reconozco",
            "is_clarification": True,
        },
    )
    assert clarified.status_code == 200, clarified.text
    assert clarified.json()["next_action"] == "CONFIRM"
    payload = {
        "requirement_id": clarified.json()["requirement_id"],
        "confirmed": False,
    }

    first_rejection = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json=payload,
    )
    repeated_rejection = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json=payload,
    )
    assert first_rejection.status_code == 200, first_rejection.text
    assert repeated_rejection.status_code == 200, repeated_rejection.text
    assert repeated_rejection.json() == first_rejection.json()

    async with TestSession() as db:
        requirements = list(
            await db.scalars(
                select(Requirement).where(
                    Requirement.session_id == UUID(session_id),
                )
            )
        )
        assert len(requirements) == 2
        assert all(requirement.active is False for requirement in requirements)


async def test_unknown_identifier_still_creates_ticket_for_manual_verification(
    client: AsyncClient,
) -> None:
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    turn = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": "Tengo un movimiento no reconocido"},
    )
    requirement_id = turn.json()["requirement_id"]
    confirmation = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json={"requirement_id": requirement_id, "confirmed": True},
    )
    assert confirmation.status_code == 200, confirmation.text

    invalid_identification = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/identification",
        headers=headers,
        json={"identifier": "CLI-1001"},
    )
    assert invalid_identification.status_code == 422, invalid_identification.text
    assert invalid_identification.json()["code"] == "VALIDATION_ERROR"

    identification = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/identification",
        headers=headers,
        json={"identifier": "9999999"},
    )
    assert identification.status_code == 200, identification.text
    result = identification.json()
    assert result["next_action"] == "COMPLETE"
    assert result["identification_status"] == "FALLIDO"
    assert result["ticket"] is not None
    assert result["requirement_id"] == requirement_id
