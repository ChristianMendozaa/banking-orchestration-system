import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import AppError
from app.domain.enums import Category, ConsultationLevel
from app.domain.schemas import ClassificationDecision, GroundedAnswerDecision
from app.services import retention
from app.services.openai_provider import OpenAIProvider
from tests.conftest import settings_for_tests


def _provider() -> OpenAIProvider:
    provider = object.__new__(OpenAIProvider)
    provider.settings = settings_for_tests
    provider.client = SimpleNamespace(
        responses=SimpleNamespace(parse=AsyncMock()),
        embeddings=SimpleNamespace(create=AsyncMock()),
    )
    return provider


async def test_openai_provider_parses_structured_outputs_and_batches_embeddings() -> None:
    provider = _provider()
    decision = ClassificationDecision(
        category=Category.CONSULTA_GENERAL,
        consultation_level=ConsultationLevel.GENERAL,
        confidence=0.9,
        ambiguous=False,
        summary="Consulta de horarios",
        customer_summary="Necesitas conocer los horarios de atención.",
    )
    provider.client.responses.parse.side_effect = [
        SimpleNamespace(output_parsed=decision),
        SimpleNamespace(
            output_parsed=GroundedAnswerDecision(
                answer="Atención de lunes a viernes.",
                supported=True,
                cited_chunk_ids=[],
            )
        ),
    ]
    assert await provider.classify("horarios") == decision

    chunk = SimpleNamespace(
        chunk=SimpleNamespace(id="chunk-1", page=1, content="Atención de lunes a viernes."),
        document=SimpleNamespace(title="Horarios"),
    )
    grounded = await provider.grounded_answer("horarios", [chunk])
    assert grounded.supported is True

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


async def test_openai_provider_rejects_missing_structured_outputs() -> None:
    provider = _provider()
    provider.client.responses.parse.return_value = SimpleNamespace(output_parsed=None)
    with pytest.raises(ValueError, match="clasificacion estructurada"):
        await provider.classify("consulta")
    with pytest.raises(ValueError, match="respuesta fundamentada"):
        await provider.grounded_answer("consulta", [])


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
