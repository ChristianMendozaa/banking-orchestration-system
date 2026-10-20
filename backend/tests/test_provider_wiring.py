import pytest
from pydantic import SecretStr

from app.api import deps
from app.services.anthropic_provider import AnthropicProvider
from app.services.openai_provider import OpenAIProvider
from tests.conftest import settings_for_tests

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def test_orchestrator_routes_decisions_to_claude_and_vectors_to_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_for_tests.model_copy(
        update={
            "anthropic_api_key": SecretStr("sk-ant-test"),
            "openai_api_key": SecretStr("sk-test"),
        }
    )
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    for cached in (deps.get_openai_provider, deps.get_anthropic_provider, deps.get_orchestrator):
        cached.cache_clear()
    try:
        orchestrator = deps.get_orchestrator()
        knowledge = orchestrator.initial_attention.knowledge
        assert isinstance(orchestrator.classifier.provider, AnthropicProvider)
        assert isinstance(knowledge.answerer, AnthropicProvider)
        assert isinstance(knowledge.provider, OpenAIProvider)
        assert isinstance(orchestrator.derivation.provider, OpenAIProvider)
    finally:
        for cached in (
            deps.get_openai_provider,
            deps.get_anthropic_provider,
            deps.get_orchestrator,
        ):
            cached.cache_clear()


def test_providers_are_absent_without_their_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps, "get_settings", lambda: settings_for_tests)
    deps.get_openai_provider.cache_clear()
    deps.get_anthropic_provider.cache_clear()
    try:
        assert deps.get_anthropic_provider() is None
        assert deps.get_openai_provider() is None
    finally:
        deps.get_openai_provider.cache_clear()
        deps.get_anthropic_provider.cache_clear()
