from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from app.api.deps import get_orchestrator
from app.db.models import CaseRecord, Identification, KioskSession, Requirement, Ticket, TraceEvent
from app.domain.enums import Category, ConsultationLevel
from app.domain.schemas import ClassificationDecision
from app.knowledge.service import KnowledgeService
from app.main import app
from app.services.agents import (
    ClassificationAgent,
    DerivationAgent,
    InitialAttentionAgent,
    PrioritizationAgent,
)
from app.services.orchestrator import OrchestratorService
from app.services.pii import PIIMaskingService
from tests.conftest import TestSession, settings_for_tests, test_orchestrator


async def _session(client: AsyncClient) -> tuple[str, str]:
    response = await client.post("/api/v1/kiosk/sessions", json={})
    assert response.status_code == 201, response.text
    data = response.json()
    return data["session_id"], data["session_token"]


async def test_general_query_is_masked_and_resolved_automatically(client: AsyncClient) -> None:
    """A GENERAL-level request never asks "Me confirmas si...?" -- see
    `turn_nodes.requires_confirmation` -- so it must resolve straight from `/turns`, with
    `next_action="COMPLETE"` and the answer embedded in `result`."""
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
    assert analysis["next_action"] == "COMPLETE"
    assert analysis["category"] == "CONSULTA_GENERAL"
    assert "EMAIL" in analysis["pii_types"]

    result = analysis["result"]
    assert result["resolution_type"] == "AUTOMATIC"
    assert result["grounding_status"] == "GROUNDED"
    assert result["citations"][0]["title"] == "Horarios de atención"
    assert result["ticket"]["status"] == "CERRADO"
    assert result["ticket"]["estimated_wait_minutes"] == 0
    assert result["response"]

    async with TestSession() as db:
        requirement = await db.scalar(select(Requirement))
        assert requirement is not None
        assert requirement.confirmation_decision is True
        assert "cliente@example.com" not in requirement.masked_text
        assert "[EMAIL]" in requirement.masked_text


async def test_an_answered_question_is_never_handed_a_reference_number(
    client: AsyncClient,
) -> None:
    """The case and its closed ticket stay -- that is what the operational reporting counts
    -- but nothing about them reaches the person who asked.

    Someone who asked what time the branch opens did not ask to be put in a queue. Telling
    them to keep a ticket number reads as the conversation being over and as a queue they
    never joined, which is exactly what it looked like on screen.
    """
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    turn = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={
            "turn_id": str(uuid4()),
            "transcript": "Quiero conocer el horario de atencion",
        },
    )
    assert turn.status_code == 200, turn.text
    result = turn.json()["result"]

    assert result["resolution_type"] == "AUTOMATIC"
    assert result["tracking_information"] is None
    assert "ticket" not in result["speech_text"].lower()
    # The record itself is untouched: the case is still closed against a ticket.
    assert result["ticket"]["status"] == "CERRADO"
    # And the conversation is left open rather than ended.
    assert result["speech_text"].rstrip().endswith("¿Te ayudo con algo más?")


async def test_asking_to_be_attended_is_honoured_over_answering_the_question(
    client: AsyncClient,
) -> None:
    """A public question the kiosk could answer, from someone who said they would rather
    see a person.

    Before this, nothing in the system represented the difference. The classifier graded the
    topic -- branch hours, CONSULTA_GENERAL, GENERAL -- retrieval succeeded, and the request
    to be attended was answered with a policy paragraph. Whether to join a queue is the
    customer's call, not the topic's.
    """
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    turn = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={
            "turn_id": str(uuid4()),
            "transcript": (
                "Quiero saber del horario de atencion, pero prefiero que me atienda un ejecutivo"
            ),
        },
    )
    assert turn.status_code == 200, turn.text
    analysis = turn.json()
    # Going to a person is the irreversible step confirmation exists in front of, so it is
    # confirmed rather than done on the strength of one sentence.
    assert analysis["next_action"] == "CONFIRM"

    confirmation = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json={"requirement_id": analysis["requirement_id"], "confirmed": True},
    )
    assert confirmation.status_code == 200, confirmation.text
    result = confirmation.json()
    assert result["resolution_type"] == "HUMAN"
    assert result["ticket"]["status"] == "PENDIENTE"
    assert result["tracking_information"]

    async with TestSession() as db:
        requirement = await db.scalar(select(Requirement))
        assert requirement is not None
        # `create_case_for_requirement` copies this onto the case, and
        # `finalize_nodes.eligibility_gate` reads it to skip retrieval entirely.
        assert requirement.force_human is True


async def test_asking_when_executives_attend_is_still_a_question(
    client: AsyncClient,
) -> None:
    """The other half of the same rule.

    Asking *about* being attended is public information and gets answered. A floor built out
    of keywords would route every question that mentions an executive or a ticket into a
    queue, which is the failure this is meant to remove, not create.
    """
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    turn = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={
            "turn_id": str(uuid4()),
            "transcript": "Quiero saber a que hora atienden los ejecutivos en la sucursal",
        },
    )
    assert turn.status_code == 200, turn.text
    analysis = turn.json()
    # Resolved on its own turn rather than confirmed: `human_requested` would have forced a
    # confirmation step, because going to a person is not something to do on a guess.
    assert analysis["next_action"] == "COMPLETE"

    async with TestSession() as db:
        requirement = await db.scalar(select(Requirement))
        assert requirement is not None
        assert requirement.force_human is False

    # Whether the answer comes from the corpus or a person is the retrieval fixture's call
    # and not this rule's, so it is deliberately not asserted here.


async def test_replayed_turn_after_automatic_resolution_returns_the_same_result(
    client: AsyncClient,
) -> None:
    """A retried request with the same turn_id must not raise TURN_ALREADY_COMPLETED once
    the session has auto-resolved -- it should hand back the already-built result, same as
    the pre-existing AWAITING_CONFIRMATION replay guard did before GENERAL requests skipped
    confirmation."""
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    turn_id = str(uuid4())
    transcript = "Quiero conocer el horario de atencion"
    payload = {"turn_id": turn_id, "transcript": transcript}

    first = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns", headers=headers, json=payload
    )
    assert first.status_code == 200, first.text
    assert first.json()["next_action"] == "COMPLETE"

    replay = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns", headers=headers, json=payload
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["requirement_id"] == first.json()["requirement_id"]
    assert replay.json()["result"]["ticket"]["number"] == first.json()["result"]["ticket"]["number"]

    async with TestSession() as db:
        tickets = list(await db.scalars(select(Ticket)))
        assert len(tickets) == 1


async def test_follow_up_turn_after_automatic_resolution_opens_a_second_case(
    client: AsyncClient,
) -> None:
    """A public-information question resolves on its own turn and closes its ticket, but the
    person is still standing at the kiosk. `cases.session_id` is no longer unique, so a
    genuinely new question (a different turn_id) opens a second case and a second ticket in
    the same session instead of being rejected."""
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    first = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": "Quiero conocer el horario de atencion"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["next_action"] == "COMPLETE"

    second = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": "Ahora quiero saber sobre creditos"},
    )
    assert second.status_code == 200, second.text

    async with TestSession() as db:
        cases = list(
            await db.scalars(select(CaseRecord).where(CaseRecord.session_id == UUID(session_id)))
        )
        assert len(cases) == 2
        assert len({case.requirement_id for case in cases}) == 2
        tickets = list(await db.scalars(select(Ticket)))
        assert len(tickets) == 2


async def test_a_request_needing_confirmation_after_earlier_answers_can_be_confirmed(
    client: AsyncClient,
) -> None:
    """The third question in a session is still the customer's own question.

    A requirement awaiting confirmation has no case yet -- the case is created when the "sí"
    arrives -- but the guard that rejects a stale confirmation used to compare it against the
    newest *case* in the session. Once a session could hold several, every automatic answer
    left a case behind, so anyone who asked something answerable before asking for something
    that needs confirming had their confirmation rejected as belonging to a previous request.
    Ask about opening hours, ask about credit requirements, then ask for something a person
    has to handle: the confirmation must be accepted.
    """
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}

    for transcript in (
        "Quiero conocer el horario de atencion",
        "Y cual es el horario los sabados",
    ):
        answered = await client.post(
            f"/api/v1/kiosk/sessions/{session_id}/turns",
            headers=headers,
            json={"turn_id": str(uuid4()), "transcript": transcript},
        )
        assert answered.status_code == 200, answered.text
        assert answered.json()["next_action"] == "COMPLETE"

    asked = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": "Quiero denunciar un fraude en mi cuenta"},
    )
    assert asked.status_code == 200, asked.text
    assert asked.json()["next_action"] == "CONFIRM"

    confirmed = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json={"requirement_id": asked.json()["requirement_id"], "confirmed": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["next_action"] != "COMPLETE" or confirmed.json()["resolution_type"]


async def test_new_turn_after_human_handoff_is_rejected(client: AsyncClient) -> None:
    """The other half of the rule: once a case is ASSIGNED, an executive owns it. The kiosk
    must not open a parallel case behind a person who is already working the queue."""
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    turn = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": "Me robaron mi tarjeta, quiero bloquearla"},
    )
    assert turn.status_code == 200, turn.text
    requirement_id = turn.json()["requirement_id"]
    confirmation = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=headers,
        json={"requirement_id": requirement_id, "confirmed": True},
    )
    assert confirmation.status_code == 200, confirmation.text
    identification = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/identification",
        headers=headers,
        json={"identifier": "6735666"},
    )
    assert identification.status_code == 200, identification.text
    assert identification.json()["status"] == "ASSIGNED"

    rejected = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={"turn_id": str(uuid4()), "transcript": "Ahora quiero saber sobre creditos"},
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "INVALID_SESSION_STATE"


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
    assert analysis["next_action"] == "COMPLETE"
    result = analysis["result"]
    assert result["resolution_type"] == "HUMAN"
    assert result["grounding_status"] == "NO_EVIDENCE"
    assert result["citations"] == []


async def test_general_inquiry_outside_consulta_general_reports_true_no_evidence(
    client: AsyncClient,
) -> None:
    """Regression test: route_human used to label grounding_status NO_EVIDENCE only when
    category was CONSULTA_GENERAL, so a real "we searched and found nothing" for every other
    category was misreported as NOT_APPLICABLE ("we never searched") -- unexplainable from
    the session state alone. It must now report NO_EVIDENCE for any GENERAL-level case that
    genuinely went through grounding, and log a RAG_NO_EVIDENCE trace event."""
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    turn = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=headers,
        json={
            "turn_id": str(uuid4()),
            "transcript": "Qué requisitos necesito para solicitar un crédito de consumo",
        },
    )
    assert turn.status_code == 200, turn.text
    analysis = turn.json()
    assert analysis["category"] == "SOLICITUD_CREDITO"
    assert analysis["consultation_level"] == "GENERAL"
    assert analysis["next_action"] == "COMPLETE"

    result = analysis["result"]
    assert result["resolution_type"] == "HUMAN"
    assert result["grounding_status"] == "NO_EVIDENCE"

    async with TestSession() as db:
        events = list(
            await db.scalars(select(TraceEvent).where(TraceEvent.event_type == "RAG_NO_EVIDENCE"))
        )
        assert len(events) == 1


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


async def test_out_of_scope_request_is_declined_without_case_or_ticket(
    client: AsyncClient,
) -> None:
    """The kiosk has a fixed set of banking services and no privileged mode to unlock. A
    classifier decision marked out_of_scope must end the session in DECLINED without ever
    creating a CaseRecord or a Ticket -- unlike force_human, which still produces both."""

    class OutOfScopeProvider:
        async def classify(self, _: str) -> ClassificationDecision:
            return ClassificationDecision(
                summary="Pide recomendacion de restaurante y clima, ajeno a la banca",
                customer_summary="Necesitas orientación sobre una consulta bancaria.",
                category=Category.CONSULTA_GENERAL,
                consultation_level=ConsultationLevel.GENERAL,
                confidence=0.95,
                ambiguous=False,
                out_of_scope=True,
            )

    provider = OutOfScopeProvider()
    declining_orchestrator = OrchestratorService(
        settings=settings_for_tests,
        pii=PIIMaskingService(),
        classifier=ClassificationAgent(settings_for_tests, provider),
        prioritizer=PrioritizationAgent(),
        derivation=DerivationAgent(provider),
        initial_attention=InitialAttentionAgent(KnowledgeService(settings_for_tests, provider)),
    )
    app.dependency_overrides[get_orchestrator] = lambda: declining_orchestrator
    try:
        session_id, token = await _session(client)
        headers = {"X-Session-Token": token}
        turn = await client.post(
            f"/api/v1/kiosk/sessions/{session_id}/turns",
            headers=headers,
            json={
                "turn_id": str(uuid4()),
                "transcript": "Recomiendame un restaurante y dime el clima de mañana",
            },
        )
        assert turn.status_code == 200, turn.text
        analysis = turn.json()
        assert analysis["next_action"] == "DECLINE"
        assert analysis["status"] == "DECLINED"

        snapshot = await client.get(
            f"/api/v1/kiosk/sessions/{session_id}",
            headers=headers,
        )
        assert snapshot.status_code == 200
        assert snapshot.json()["analysis"] == analysis
        assert snapshot.json()["result"] is None
    finally:
        app.dependency_overrides[get_orchestrator] = lambda: test_orchestrator

    async with TestSession() as db:
        cases = list(await db.scalars(select(CaseRecord)))
        tickets = list(await db.scalars(select(Ticket)))
        assert cases == []
        assert tickets == []


async def test_general_label_on_a_fraud_report_still_requires_identification(
    client: AsyncClient,
) -> None:
    """The failure mode of the 2026-08-18 eval run, pinned: the classifier returned GENERAL
    at 0.99 confidence for a first-person fraud report, which under a GENERAL-means-skip
    policy closed the ticket without ever asking who the customer was. Two things must now
    stop that -- `sensitivity_floor` raises the level, and `requires_confirmation` refuses to
    auto-resolve a REPORTE_FRAUDE -- so the case comes out PENDIENTE, not ANONIMO."""

    class UnderLabellingProvider:
        async def classify(self, _: str) -> ClassificationDecision:
            return ClassificationDecision(
                summary="Reporta un cargo no reconocido en su tarjeta",
                customer_summary="Necesitas reportar un cargo que no reconoces.",
                category=Category.REPORTE_FRAUDE,
                consultation_level=ConsultationLevel.GENERAL,
                confidence=0.99,
                ambiguous=False,
            )

    provider = UnderLabellingProvider()
    orchestrator = OrchestratorService(
        settings=settings_for_tests,
        pii=PIIMaskingService(),
        classifier=ClassificationAgent(settings_for_tests, provider),
        prioritizer=PrioritizationAgent(),
        derivation=DerivationAgent(provider),
        initial_attention=InitialAttentionAgent(KnowledgeService(settings_for_tests, provider)),
    )
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    try:
        session_id, token = await _session(client)
        headers = {"X-Session-Token": token}
        turn = await client.post(
            f"/api/v1/kiosk/sessions/{session_id}/turns",
            headers=headers,
            json={
                "turn_id": str(uuid4()),
                "transcript": "Me apareció un cargo que no reconozco en mi tarjeta",
            },
        )
        assert turn.status_code == 200, turn.text
        analysis = turn.json()
        assert analysis["next_action"] == "CONFIRM"
        assert analysis["consultation_level"] == "SENSIBLE"

        confirmation = await client.post(
            f"/api/v1/kiosk/sessions/{session_id}/confirmation",
            headers=headers,
            json={"requirement_id": analysis["requirement_id"], "confirmed": True},
        )
        assert confirmation.status_code == 200, confirmation.text
        assert confirmation.json()["next_action"] == "IDENTIFY"
    finally:
        app.dependency_overrides[get_orchestrator] = lambda: test_orchestrator

    async with TestSession() as db:
        case = await db.scalar(select(CaseRecord))
        assert case is not None
        assert case.consultation_level is ConsultationLevel.SENSIBLE
        assert case.identification_status.value == "PENDIENTE"
        requirement = await db.scalar(select(Requirement))
        assert requirement is not None
        assert requirement.classification_source == "MODEL+FLOOR"


async def test_repeated_corrections_hand_the_session_to_a_person(client: AsyncClient) -> None:
    """A customer who cannot phrase the request used to loop CONFIRM -> reject -> CAPTURE
    forever and leave with no ticket at all (`cliente_no_entiende_la_pregunta`, 2/10, ending
    in LISTENING). After `max_corrections` rejections the kiosk stops re-asking and routes
    the case to an executive, skipping RAG on force_human."""
    session_id, token = await _session(client)
    headers = {"X-Session-Token": token}
    last: dict = {}
    for _ in range(settings_for_tests.max_corrections):
        turn = await client.post(
            f"/api/v1/kiosk/sessions/{session_id}/turns",
            headers=headers,
            json={"turn_id": str(uuid4()), "transcript": "Quiero bloquear mi tarjeta"},
        )
        assert turn.status_code == 200, turn.text
        assert turn.json()["next_action"] == "CONFIRM"
        rejection = await client.post(
            f"/api/v1/kiosk/sessions/{session_id}/confirmation",
            headers=headers,
            json={"requirement_id": turn.json()["requirement_id"], "confirmed": False},
        )
        assert rejection.status_code == 200, rejection.text
        last = rejection.json()

    assert last["next_action"] == "COMPLETE"
    assert last["resolution_type"] == "HUMAN"
    assert last["ticket"]["number"]

    async with TestSession() as db:
        session_row = await db.scalar(select(KioskSession))
        assert session_row is not None
        assert session_row.status.value == "ASSIGNED"
        case = await db.scalar(select(CaseRecord))
        assert case is not None and case.force_human is True
        events = list(await db.scalars(select(TraceEvent)))
        assert any(event.event_type == "CORRECTION_LIMIT_REACHED" for event in events)
