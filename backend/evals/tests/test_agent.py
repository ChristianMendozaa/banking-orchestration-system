"""Verifies the customer agent's wiring compiles correctly.

Does not call agent.run() -- that needs a real OpenAI API key and costs real money. The
fake key here only satisfies OpenAIChatCompletionClient's eager credential check at
construction time; no network call happens.
"""

import pytest

from harness.agent import build_customer_agent
from harness.client import KioskClient, SessionHandle
from harness.personas import PERSONAS
from harness.session import ConversationSession


@pytest.fixture(autouse=True)
def _fake_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-for-wiring-check")


def _session() -> ConversationSession:
    return ConversationSession(KioskClient("http://fake"), SessionHandle("sid", "tok"))


def test_agent_is_built_with_the_expected_name() -> None:
    agent = build_customer_agent(model="gpt-4o-mini", session=_session(), persona=PERSONAS[0])
    assert agent.name == "cliente_simulado"


def test_agent_system_message_embeds_the_persona_goal() -> None:
    persona = PERSONAS[0]
    agent = build_customer_agent(model="gpt-4o-mini", session=_session(), persona=persona)
    assert persona.goal in agent._system_messages[0].content


def test_agent_has_three_tools_bound_to_the_session() -> None:
    session = _session()
    agent = build_customer_agent(model="gpt-4o-mini", session=session, persona=PERSONAS[0])
    tool_names = {tool.name for tool in agent._tools}
    assert tool_names == {"send_turn", "send_confirmation", "send_identification"}
