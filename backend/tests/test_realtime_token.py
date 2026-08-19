from uuid import UUID

import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from app.api.deps import get_openai_provider
from app.db.models import KioskSession
from app.domain.enums import SessionStatus
from app.main import app
from app.services.openai_provider import OpenAIProvider
from tests.conftest import TestSession


class FakeRealtimeProvider:
    async def create_realtime_client_secret(self, safety_identifier: str):
        assert safety_identifier
        return {
            "value": "ephemeral-test-token",
            "expires_at": 1_800_000_000,
            "session": {"model": "gpt-realtime-2.1"},
        }


async def test_realtime_endpoint_only_returns_ephemeral_secret(client: AsyncClient) -> None:
    app.dependency_overrides[get_openai_provider] = lambda: FakeRealtimeProvider()
    try:
        created = await client.post("/api/v1/kiosk/sessions", json={})
        session_id = created.json()["session_id"]
        response = await client.post(
            f"/api/v1/kiosk/sessions/{session_id}/realtime-token",
            headers={"X-Session-Token": created.json()["session_token"]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["value"] == "ephemeral-test-token"
        assert "OPENAI_API_KEY" not in response.text
    finally:
        app.dependency_overrides.pop(get_openai_provider, None)


@pytest.mark.parametrize(
    "status",
    [
        SessionStatus.NEEDS_CLARIFICATION,
        SessionStatus.AWAITING_CONFIRMATION,
        SessionStatus.AWAITING_IDENTIFICATION,
    ],
)
async def test_realtime_endpoint_preserves_resumable_state(
    client: AsyncClient, status: SessionStatus
) -> None:
    app.dependency_overrides[get_openai_provider] = lambda: FakeRealtimeProvider()
    try:
        created = await client.post("/api/v1/kiosk/sessions", json={})
        data = created.json()
        async with TestSession() as db:
            kiosk_session = await db.get(KioskSession, UUID(data["session_id"]))
            assert kiosk_session is not None
            kiosk_session.status = status
            await db.commit()

        response = await client.post(
            f"/api/v1/kiosk/sessions/{data['session_id']}/realtime-token",
            headers={"X-Session-Token": data["session_token"]},
        )
        assert response.status_code == 200, response.text

        async with TestSession() as db:
            kiosk_session = await db.get(KioskSession, UUID(data["session_id"]))
            assert kiosk_session is not None
            assert kiosk_session.status == status
    finally:
        app.dependency_overrides.pop(get_openai_provider, None)


async def test_realtime_session_enables_conversation_and_interruptions(
    monkeypatch, settings
) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"value": "ephemeral", "session": {}}

    class FakeHTTPClient:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, url, json, headers):
            captured.update(url=url, json=json, headers=headers)
            return FakeResponse()

    monkeypatch.setattr("app.services.openai_provider.httpx.AsyncClient", FakeHTTPClient)
    configured = settings.model_copy(update={"openai_api_key": SecretStr("test-key")})
    await OpenAIProvider(configured).create_realtime_client_secret("session-test")
    session = captured["json"]["session"]
    turn_detection = session["audio"]["input"]["turn_detection"]
    assert session["model"] == "gpt-realtime-2.1"
    assert session["output_modalities"] == ["audio"]
    assert session["audio"]["input"]["transcription"]["model"] == "gpt-realtime-whisper"
    assert session["audio"]["output"]["voice"] == "marin"
    assert "Dirígete siempre de tú" in session["instructions"]
    assert "pronúncialo una sola vez" in session["instructions"]
    assert turn_detection == {
        "type": "semantic_vad",
        "eagerness": "auto",
        "create_response": True,
        "interrupt_response": True,
    }
    assert captured["url"].endswith("/v1/realtime/client_secrets")
