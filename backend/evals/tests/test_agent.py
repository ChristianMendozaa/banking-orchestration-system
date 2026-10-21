"""The simulated customer's wiring and its tool loop.

The loop runs against a patched `AsyncMessages.create` -- a real request needs a real key
and costs money. The fake key in `conftest` only satisfies the client's construction-time
credential check.
"""

import inspect
from unittest.mock import AsyncMock, patch

from anthropic import AsyncAnthropic
from anthropic.resources.messages import AsyncMessages
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from conftest import make_scenario

from harness.agent import (
    CUSTOMER_TOOLS,
    MAX_TOOL_ITERATIONS,
    build_customer_agent,
    build_system_message,
)
from harness.client import SessionHandle
from harness.scenarios.models import ANGUSTIADO
from harness.session import ConversationSession

KIOSK_CONFIRMS = {
    "next_action": "CONFIRM",
    "requirement_id": "req-1",
    "speech_text": "¿Quieres bloquear tu tarjeta?",
}


def _session() -> ConversationSession:
    client = AsyncMock()
    client.send_turn.return_value = KIOSK_CONFIRMS
    return ConversationSession(client, SessionHandle("sid", "tok"))


def _reply(*content, stop_reason: str = "end_turn") -> Message:
    return Message(
        id="msg",
        type="message",
        role="assistant",
        model="claude-haiku-5-5",
        content=list(content),
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def _tool_use(name: str, arguments: dict, tool_use_id: str = "toolu_1") -> Message:
    block = ToolUseBlock(type="tool_use", id=tool_use_id, name=name, input=arguments)
    return _reply(block, stop_reason="tool_use")


TERMINATE = _reply(TextBlock(type="text", text="TERMINATE"))
SEND_TURN = _tool_use(
    "send_turn", {"transcript": "Me robaron la tarjeta", "is_clarification": False}
)


async def _run(session: ConversationSession, *replies: Message) -> list[dict]:
    """Runs the customer against scripted model replies and returns each request as it was
    sent. The loop keeps appending to one `messages` list, so each request's list is copied
    when it is made -- reading `call_args` afterwards would show only the final history."""
    requests: list[dict] = []
    remaining = iter(replies)

    async def create(_self, **request):
        requests.append({**request, "messages": list(request["messages"])})
        return next(remaining)

    agent = build_customer_agent(
        client=AsyncAnthropic(),
        model="claude-haiku-5-5",
        session=session,
        scenario=make_scenario(identifier="6735666"),
    )
    # `create` is wrapped by the SDK's argument-checking decorator, so autospec does not
    # see it as a coroutine function; the async side effect makes the call awaitable. The
    # autospec holds every request to the installed SDK's real signature, which a
    # hand-written mock would not.
    with patch.object(AsyncMessages, "create", autospec=True, side_effect=create):
        await agent.run(task="Empieza.")
    return requests


def test_each_declared_tool_matches_a_session_method() -> None:
    """The schemas are written by hand, so this is what stops one drifting from the method
    it dispatches to: same name, and exactly the method's parameters, all required."""
    assert {tool["name"] for tool in CUSTOMER_TOOLS} == {
        "send_turn",
        "send_confirmation",
        "send_identification",
    }
    for tool in CUSTOMER_TOOLS:
        method = getattr(ConversationSession, tool["name"])
        parameters = [name for name in inspect.signature(method).parameters if name != "self"]
        assert tool["input_schema"]["required"] == parameters
        assert set(tool["input_schema"]["properties"]) == set(parameters)
        assert tool["description"] == inspect.getdoc(method)


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


async def test_a_tool_call_reaches_the_kiosk_and_its_answer_goes_back_to_the_model() -> None:
    session = _session()
    requests = await _run(session, SEND_TURN, TERMINATE)

    session._client.send_turn.assert_awaited_once()
    assert session.customer_utterances == ["Me robaron la tarjeta"]
    assert len(requests) == 2
    assistant, tool_results = requests[1]["messages"][1:]
    assert assistant == {"role": "assistant", "content": SEND_TURN.content}
    [result] = tool_results["content"]
    assert result["tool_use_id"] == "toolu_1"
    assert "next_action=CONFIRM" in result["content"]
    assert "is_error" not in result


async def test_a_harness_directive_follows_the_tool_result_as_a_system_message() -> None:
    """The customer model reads instructions inside a tool result as possibly injected text;
    on 2026-10-20 it answered "the session is still open" with a goodbye via send_turn
    instead of TERMINATE. The kiosk's data stays in the tool result, the instruction moves
    to its own system message, and the history is only ever appended to."""
    session = _session()
    session._client.send_turn.return_value = {
        "next_action": "COMPLETE",
        "requirement_id": "req-1",
        "speech_text": "La sucursal atiende de 08:30 a 19:00.",
        "result": {"resolution_type": "HUMAN", "conversation_can_continue": False},
    }
    requests = await _run(session, SEND_TURN, TERMINATE)

    _, _, tool_results, directive = requests[1]["messages"]
    [result] = tool_results["content"]
    assert "TERMINATE" not in result["content"]
    assert directive["role"] == "system"
    assert "TERMINATE" in directive["content"]
    assert session.take_directive() is None


async def test_the_customer_stops_when_the_model_stops_calling_tools() -> None:
    requests = await _run(_session(), TERMINATE)
    assert len(requests) == 1


async def test_the_customer_request_matches_the_installed_sdk_signature() -> None:
    """Regression: the AutoGen client this replaced always sent `temperature`, which
    `anthropic` 1.x removed from `messages.create`, so every conversational scenario failed
    with a TypeError before reaching the API."""
    [request] = await _run(_session(), TERMINATE)
    assert "temperature" not in request
    assert request["model"] == "claude-haiku-5-5"
    assert "thinking" not in request
    assert request["output_config"] == {"effort": "low"}
    assert request["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert request["tools"] == CUSTOMER_TOOLS
    assert request["system"] == build_system_message(make_scenario(identifier="6735666"))
    assert request["messages"] == [{"role": "user", "content": "Empieza."}]


async def test_a_customer_that_never_stops_calling_tools_is_cut_off() -> None:
    requests = await _run(_session(), *[SEND_TURN] * (MAX_TOOL_ITERATIONS + 5))
    assert len(requests) == MAX_TOOL_ITERATIONS


async def test_an_unknown_tool_is_reported_to_the_model_and_the_loop_continues() -> None:
    session = _session()
    requests = await _run(session, _tool_use("send_payment", {"amount": 10}), TERMINATE)
    [result] = requests[1]["messages"][-1]["content"]
    assert result["is_error"] is True
    assert "send_payment" in result["content"]
    assert session.exchanges == []


async def test_a_tool_that_raises_is_reported_to_the_model_and_the_loop_continues() -> None:
    session = _session()
    session._client.send_turn.side_effect = ValueError("respuesta ilegible")
    requests = await _run(session, SEND_TURN, TERMINATE)
    [result] = requests[1]["messages"][-1]["content"]
    assert result["is_error"] is True
    assert "ValueError: respuesta ilegible" in result["content"]
    assert len(requests) == 2


async def test_a_reply_cut_off_at_max_tokens_runs_no_tool() -> None:
    session = _session()
    block = ToolUseBlock(type="tool_use", id="toolu_1", name="send_turn", input={})
    requests = await _run(session, _reply(block, stop_reason="max_tokens"))
    assert len(requests) == 1
    session._client.send_turn.assert_not_awaited()
