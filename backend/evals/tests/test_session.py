from unittest.mock import AsyncMock

from harness.client import SessionHandle
from harness.session import ConversationSession


def _fake_client(**method_returns: dict) -> AsyncMock:
    client = AsyncMock()
    for name, value in method_returns.items():
        getattr(client, name).return_value = value
    return client


async def test_send_turn_tracks_category_and_requirement() -> None:
    client = _fake_client(
        send_turn={
            "next_action": "CONFIRM",
            "requirement_id": "req-1",
            "category": "CONSULTA_GENERAL",
            "consultation_level": "GENERAL",
        }
    )
    session = ConversationSession(client, SessionHandle("sid", "tok"))
    description = await session.send_turn("hola", False)
    assert session.last_requirement_id == "req-1"
    assert session.last_category == "CONSULTA_GENERAL"
    assert "next_action=CONFIRM" in description
    assert session.clarification_rounds == 0


async def test_clarify_action_increments_round_counter() -> None:
    client = _fake_client(
        send_turn={"next_action": "CLARIFY", "clarification_question": "¿Podrías detallar?"}
    )
    session = ConversationSession(client, SessionHandle("sid", "tok"))
    description = await session.send_turn("algo vago", False)
    assert session.clarification_rounds == 1
    assert "pregunta_aclaracion" in description


async def test_confirmation_without_prior_turn_is_rejected() -> None:
    client = _fake_client()
    session = ConversationSession(client, SessionHandle("sid", "tok"))
    description = await session.send_confirmation(True)
    assert "Error" in description
    client.send_confirmation.assert_not_called()


async def test_complete_next_action_marks_session_finished() -> None:
    client = _fake_client(
        send_turn={
            "next_action": "CONFIRM",
            "requirement_id": "req-1",
            "category": "CONSULTA_GENERAL",
        },
        send_confirmation={"next_action": "COMPLETE", "speech_text": "Listo"},
    )
    session = ConversationSession(client, SessionHandle("sid", "tok"))
    await session.send_turn("hola", False)
    description = await session.send_confirmation(True)
    assert session.finished is True
    assert "TERMINATE" in description


async def test_log_records_every_tool_call() -> None:
    client = _fake_client(
        send_turn={"next_action": "CONFIRM", "requirement_id": "req-1", "category": "X"}
    )
    session = ConversationSession(client, SessionHandle("sid", "tok"))
    await session.send_turn("hola", False)
    assert len(session.log) == 1
    assert session.log[0]["tool"] == "send_turn"
