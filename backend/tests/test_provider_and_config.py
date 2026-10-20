import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import ROOT_ENV_FILE, Settings
from app.core.errors import AppError
from app.services import retention
from app.services.openai_provider import OpenAIProvider
from tests.conftest import settings_for_tests

pytestmark = [pytest.mark.unit]


def _provider() -> OpenAIProvider:
    provider = object.__new__(OpenAIProvider)
    provider.settings = settings_for_tests
    provider.client = SimpleNamespace(embeddings=SimpleNamespace(create=AsyncMock()))
    return provider


async def test_openai_provider_batches_embeddings() -> None:
    provider = _provider()
    provider.client.embeddings.create.side_effect = [
        SimpleNamespace(
            data=[
                SimpleNamespace(index=index, embedding=[float(index)])
                for index in reversed(range(64))
            ]
        ),
        SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[64.0])]),
    ]
    vectors = await provider.embeddings([str(index) for index in range(65)])
    assert vectors == [[float(index)] for index in range(65)]
    assert await provider.embeddings([]) == []


async def test_realtime_http_failure_uses_public_error(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider()

    class BrokenClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, *_args, **_kwargs):
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: BrokenClient())
    with pytest.raises(AppError) as caught:
        await provider.create_realtime_client_secret("session-hash")
    assert caught.value.code == "REALTIME_UNAVAILABLE"


async def test_retention_loop_logs_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    stop = asyncio.Event()
    purge = AsyncMock(side_effect=[2])
    logged = []

    async def wait_and_stop(awaitable, *, timeout):
        assert timeout == settings_for_tests.conversation_cleanup_hours * 3600
        stop.set()
        return await awaitable

    monkeypatch.setattr(retention, "purge_expired_conversations", purge)
    monkeypatch.setattr(retention.asyncio, "wait_for", wait_and_stop)
    monkeypatch.setattr(
        retention.logger, "info", lambda event, **data: logged.append((event, data))
    )
    await retention.conversation_retention_loop(settings_for_tests, stop)
    assert logged == [("conversation_retention_purged", {"deleted": 2})]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("embedding_dimensions", 0),
        ("rag_top_k", 0),
        ("rag_min_score", 1.1),
        ("rag_chunk_tokens", 99),
        ("rag_chunk_overlap", 600),
        ("kiosk_session_minutes", 0),
        ("kiosk_max_turns", 0),
        ("kiosk_follow_up_inactivity_seconds", 0),
        ("knowledge_max_upload_mb", 0),
        ("knowledge_max_pages", 0),
        ("dashboard_refresh_ms", 999),
        ("estimated_service_minutes", 0),
        ("conversation_retention_days", 0),
        ("conversation_cleanup_hours", 0),
    ],
)
def test_settings_reject_invalid_operational_limits(field: str, value: object) -> None:
    payload = settings_for_tests.model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        Settings.model_validate(payload)


def test_settings_read_the_single_root_env_file() -> None:
    # One .env at the repository root serves the backend, Compose and the frontend; it is
    # located from the module, not the working directory, so `cd backend` is not required.
    repo_root = ROOT_ENV_FILE.parent
    assert ROOT_ENV_FILE.name == ".env"
    assert (repo_root / "docker-compose.yml").is_file()
    assert (repo_root / "backend" / "pyproject.toml").is_file()


def test_settings_default_to_claude_haiku_for_orchestration() -> None:
    assert Settings.model_fields["orchestration_model"].default == "claude-haiku-5-5"
    assert settings_for_tests.anthropic_enabled is False
    enabled = Settings.model_validate(
        {**settings_for_tests.model_dump(), "anthropic_api_key": "sk-ant-test"}
    )
    assert enabled.anthropic_enabled is True


@pytest.mark.parametrize("field", ["classification_reasoning_effort", "grounding_reasoning_effort"])
def test_settings_reject_effort_levels_the_orchestration_model_lacks(field: str) -> None:
    # "none" was valid on gpt-5.4-mini; Claude Haiku 5.5 rejects it, so it must fail at
    # startup instead of on the first customer turn.
    payload = settings_for_tests.model_dump()
    payload[field] = "none"
    with pytest.raises(ValidationError):
        Settings.model_validate(payload)


@pytest.mark.parametrize(
    ("missing", "message"),
    [("anthropic_api_key", "ANTHROPIC_API_KEY"), ("openai_api_key", "OPENAI_API_KEY")],
)
def test_production_requires_both_model_providers(missing: str, message: str) -> None:
    payload = {
        **settings_for_tests.model_dump(),
        "app_env": "production",
        "identifier_encryption_keys": {"prod-v1": "A" * 43 + "="},
        "identifier_active_key_id": "prod-v1",
        "redis_url": "redis://redis:6379/0",
        "clamav_host": "clamav",
        "metrics_token": "m" * 32,
        "anthropic_api_key": "sk-ant-test",
        "openai_api_key": "sk-test",
    }
    payload[missing] = ""
    with pytest.raises(ValidationError, match=message):
        Settings.model_validate(payload)
