"""The simulated customer's wiring.

Does not call `agent.run()` -- that needs a real key and costs money. The fake key in
`conftest` only satisfies the client's construction-time credential check.
"""

from unittest.mock import AsyncMock, patch

from anthropic.resources.messages import AsyncMessages
from anthropic.types import Message, TextBlock, Usage
from autogen_core.models import SystemMessage, UserMessage
from autogen_core.tools import FunctionTool
from conftest import make_scenario

from harness.agent import build_customer_agent, build_system_message
from harness.client import KioskClient, SessionHandle
from harness.model_client import build_customer_client
from harness.scenarios import SCENARIOS
from harness.scenarios.models import ANGUSTIADO
from harness.session import ConversationSession


def _session() -> ConversationSession:
    return ConversationSession(KioskClient("http://fake"), SessionHandle("sid", "tok"))


def test_agent_binds_exactly_the_three_kiosk_tools() -> None:
    agent = build_customer_agent(
        model_client=build_customer_client("claude-haiku-5-5"),
        session=_session(),
        scenario=SCENARIOS[0],
    )
    assert agent.name == "cliente_simulado"
    assert {tool.name for tool in agent._tools} == {
        "send_turn",
        "send_confirmation",
        "send_identification",
    }


def test_system_message_combines_the_situation_and_the_speaking_style() -> None:
    """Goal and style are separate fields precisely so the same situation can be re-tested
    through a different mouth -- both have to reach the prompt."""
    scenario = make_scenario(goal="Te robaron la tarjeta.", style=ANGUSTIADO)
    message = build_system_message(scenario)
    assert "Te robaron la tarjeta." in message
    assert ANGUSTIADO.instruction in message


def test_a_scenario_with_an_identifier_tells_the_customer_which_ci_to_give() -> None:
    message = build_system_message(make_scenario(identifier="6735666"))
    assert "6735666" in message


def test_a_scenario_without_an_identifier_forbids_inventing_one() -> None:
    message = build_system_message(make_scenario(identifier=None))
    assert "inventar" in message


def test_a_customer_without_a_ci_is_not_told_to_answer_with_a_turn() -> None:
    """The state machine rejects a turn while the session is AWAITING_IDENTIFICATION, so
    telling the persona to explain itself that way manufactures a 409 the kiosk is not
    responsible for -- which is exactly what an earlier version of this prompt did."""
    message = build_system_message(make_scenario(identifier=None))
    no_ci_clause = message.split("No tienes ningun documento")[1].split("\n")[0]
    assert "send_turn" not in no_ci_clause
    assert "TERMINATE" in message


def test_the_persona_is_told_to_follow_next_action_to_the_end() -> None:
    """The customer model otherwise stops after one turn in some scenarios, leaving the session
    stranded at AWAITING_CONFIRMATION and scoring the kiosk for the harness's shortfall."""
    message = build_system_message(make_scenario())
    for action in ("CLARIFY", "CONFIRM", "IDENTIFY", "COMPLETE"):
        assert action in message
    assert "No dejes" in message


def test_a_model_missing_from_autogens_table_still_builds_a_client() -> None:
    """`autogen-ext`'s Anthropic table stops at the Claude 4 models and would reject the
    `claude-haiku-5-5` default at construction time without an explicit `model_info`."""
    client = build_customer_client("claude-haiku-5-5")
    assert client.model_info["function_calling"] is True
    assert client.model_info["structured_output"] is False


def test_the_customer_runs_without_thinking() -> None:
    """AutoGen's Anthropic client does not send thinking blocks back with tool results, so
    the customer's tool loop runs with thinking off rather than relying on that replay."""
    client = build_customer_client("claude-haiku-5-5")
    assert client._create_args["thinking"] == {"type": "disabled"}


async def _send_turn(text: str) -> str:
    """Envia un turno al kiosco."""
    return "ok"


async def test_the_customer_request_matches_the_installed_sdk_signature() -> None:
    """Regression: `autogen-ext` always sends `temperature`, which `anthropic` 1.x removed
    from `messages.create`, so every conversational scenario failed with a TypeError
    before reaching the API. `autospec` holds the call to the real SDK signature, which a
    hand-written mock would not have."""
    reply = Message(
        id="msg",
        type="message",
        role="assistant",
        model="claude-haiku-5-5",
        content=[TextBlock(type="text", text="Hola")],
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(input_tokens=1, output_tokens=1),
    )
    client = build_customer_client("claude-haiku-5-5")
    # `create` is wrapped by the SDK's argument-checking decorator, so autospec does not
    # see it as a coroutine function; the async side effect makes the call awaitable.
    with patch.object(
        AsyncMessages, "create", autospec=True, side_effect=AsyncMock(return_value=reply)
    ) as create:
        result = await client.create(
            [SystemMessage(content="sys"), UserMessage(content="hola", source="cliente")],
            tools=[FunctionTool(_send_turn, description="Envia un turno al kiosco.")],
        )
    assert result.content == "Hola"
    request = create.call_args.kwargs
    assert "temperature" not in request
    assert request["thinking"] == {"type": "disabled"}
    assert request["tool_choice"] == {"type": "auto"}
