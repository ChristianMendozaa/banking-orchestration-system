from httpx import AsyncClient
from pydantic import SecretStr

from app.api.deps import get_openai_provider
from app.main import app
from app.services.openai_provider import OpenAIProvider


class FakeRealtimeProvider:
    async def create_realtime_client_secret(self, safety_identifier: str):
        assert safety_identifier
        return {
            "value": "ephemeral-test-token",
            "expires_at": 1_800_000_000,
            "session": {"model": "gpt-realtime-2.1-mini"},
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


async def test_realtime_session_disables_autonomous_model_responses(monkeypatch, settings) -> None:
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
    turn_detection = captured["json"]["session"]["audio"]["input"]["turn_detection"]
    assert turn_detection["create_response"] is False
    assert turn_detection["interrupt_response"] is False
    assert captured["url"].endswith("/v1/realtime/client_secrets")
