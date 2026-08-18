"""Transcript capture and the state the scoring layer reads.

The customer's own words exist nowhere but here -- they are the tool arguments, and the
API never echoes them back -- so a session that fails to record them makes both the
dashboard's conversation view and the judge's dossier half-blind.
"""

from unittest.mock import AsyncMock

from harness.client import KioskClientError, SessionHandle
from harness.session import ConversationSession


def _fake_client(**method_returns) -> AsyncMock:
    client = AsyncMock()
    for name, value in method_returns.items():
        getattr(client, name).return_value = value
    return client


def _session(client) -> ConversationSession:
    return ConversationSession(client, SessionHandle("sid", "tok"))


async def test_send_turn_tracks_what_the_system_decided() -> None:
    session = _session(
        _fake_client(
            send_turn={
                "next_action": "CONFIRM",
                "requirement_id": "req-1",
                "category": "CONSULTA_GENERAL",
                "consultation_level": "GENERAL",
                "pii_types": ["TARJETA"],
            }
        )
    )
    description = await session.send_turn("hola", False)
    assert session.last_requirement_id == "req-1"
    assert session.last_category == "CONSULTA_GENERAL"
    assert session.pii_types == ["TARJETA"]
    assert session.requirement_ids == ["req-1"]
    assert "next_action=CONFIRM" in description


async def test_the_transcript_records_both_sides() -> None:
    session = _session(
        _fake_client(
            send_turn={
                "next_action": "CONFIRM",
                "requirement_id": "r",
                "speech_text": "¿Confirmas?",
            }
        )
    )
    await session.send_turn("Me robaron la tarjeta", False)
    exchange = session.exchanges[0]
    assert exchange.customer_text == "Me robaron la tarjeta"
    assert exchange.kiosk_speech == "¿Confirmas?"
    assert session.customer_utterances == ["Me robaron la tarjeta"]
    assert session.kiosk_utterances == ["¿Confirmas?"]


async def test_a_clarification_question_is_what_the_kiosk_said() -> None:
    session = _session(
        _fake_client(
            send_turn={"next_action": "CLARIFY", "clarification_question": "¿Podrías detallar?"}
        )
    )
    await session.send_turn("algo vago", False)
    assert session.clarification_rounds == 1
    assert session.kiosk_utterances == ["¿Podrías detallar?"]


async def test_rejecting_a_summary_counts_as_a_correction() -> None:
    session = _session(
        _fake_client(
            send_turn={"next_action": "CONFIRM", "requirement_id": "r"},
            send_confirmation={"next_action": "CAPTURE", "speech_text": "Cuéntame nuevamente"},
        )
    )
    await session.send_turn("quiero algo", False)
    await session.send_confirmation(False)
    assert session.correction_rounds == 1
    assert session.finished is False


async def test_a_new_requirement_after_a_correction_is_tracked_separately() -> None:
    client = _fake_client()
    client.send_turn.side_effect = [
        {"next_action": "CONFIRM", "requirement_id": "req-1"},
        {"next_action": "CONFIRM", "requirement_id": "req-2"},
    ]
    session = _session(client)
    await session.send_turn("cuentas de ahorro", False)
    await session.send_turn("no, bloquear mi tarjeta", False)
    assert session.requirement_ids == ["req-1", "req-2"]


async def test_confirmation_without_a_prior_turn_is_refused_locally() -> None:
    client = _fake_client()
    session = _session(client)
    description = await session.send_confirmation(True)
    assert "Error" in description
    client.send_confirmation.assert_not_called()


async def test_identification_attempts_are_counted() -> None:
    session = _session(_fake_client(send_identification={"next_action": "COMPLETE"}))
    await session.send_identification("6735666")
    assert session.identification_attempts == 1
    assert session.exchanges[0].customer_text == "Mi CI es 6735666."


async def test_a_completed_flow_tells_the_agent_to_stop() -> None:
    session = _session(
        _fake_client(
            send_turn={"next_action": "CONFIRM", "requirement_id": "r"},
            send_confirmation={"next_action": "COMPLETE", "speech_text": "Listo"},
        )
    )
    await session.send_turn("hola", False)
    description = await session.send_confirmation(True)
    assert session.finished is True
    assert "TERMINATE" in description


async def test_send_turn_completing_on_its_own_tells_the_agent_to_stop() -> None:
    """A confident GENERAL request now resolves on the same turn (no confirmation step)
    and returns next_action=COMPLETE directly from send_turn -- this must mark the session
    finished exactly like a COMPLETE from send_confirmation does."""
    session = _session(
        _fake_client(
            send_turn={
                "next_action": "COMPLETE",
                "requirement_id": "r",
                "speech_text": "Las agencias atienden de 09:00 a 20:00.",
            }
        )
    )
    description = await session.send_turn("horarios de atencion", False)
    assert session.finished is True
    assert "TERMINATE" in description


async def test_an_api_error_is_recorded_and_reported_back_instead_of_raising() -> None:
    """Aborting the agent loop on a mid-flow 409 would discard the transcript that
    explains it, so the error becomes a tool result and a scored failure."""
    client = _fake_client()
    client.send_turn.side_effect = KioskClientError("send_turn failed: 409 conflict")
    session = _session(client)
    description = await session.send_turn("hola", False)
    assert session.errors == ["send_turn: send_turn failed: 409 conflict"]
    assert session.exchanges[0].error is not None
    assert "TERMINATE" in description


async def test_record_raw_captures_a_protocol_exchange() -> None:
    session = _session(_fake_client())
    session.record_raw(
        "send_identification",
        "CI antes de confirmar",
        409,
        {"code": "INVALID_SESSION_STATE", "message": "La sesión no espera un CI"},
    )
    exchange = session.exchanges[0]
    assert exchange.customer_text == "CI antes de confirmar"
    assert "HTTP 409" in exchange.kiosk_speech
    assert "INVALID_SESSION_STATE" in exchange.kiosk_speech
