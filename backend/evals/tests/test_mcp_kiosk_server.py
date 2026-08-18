"""The in-process MCP server that exposes `ConversationSession`'s 3 tools to a local CLI.

Exercised against a real MCP client (`mcp.client.streamable_http`) speaking to the real
server over a real localhost socket -- the thing actually being verified is the wire
contract (tool names, descriptions, argument passing, the turn-budget stop instruction),
not a mock of it. No real backend, no real CLI (`claude`/`codex`) -- those are covered
live, not here (see `cli_customer.py`'s module docstring).
"""

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from harness.mcp_kiosk_server import MAX_TOOL_CALLS, serve_kiosk_tools


class FakeSession:
    """Stands in for `ConversationSession` -- same 3 async methods, same docstrings (the
    real ones become each MCP tool's description), but returns canned text instead of
    calling a real backend."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def send_turn(self, transcript: str, is_clarification: bool) -> str:
        """Envia lo que dice el cliente al kiosco."""
        self.calls.append(("send_turn", transcript, is_clarification))
        return "next_action=CONFIRM"

    async def send_confirmation(self, confirmed: bool) -> str:
        """Confirma o rechaza el resumen que propuso el kiosco."""
        self.calls.append(("send_confirmation", confirmed))
        return "next_action=COMPLETE"

    async def send_identification(self, identifier: str) -> str:
        """Proporciona el numero de CI del cliente."""
        self.calls.append(("send_identification", identifier))
        return "next_action=COMPLETE"


async def test_serve_kiosk_tools_exposes_the_same_three_tools_with_their_own_docstrings() -> None:
    session = FakeSession()
    async with serve_kiosk_tools(session) as url:
        async with streamable_http_client(url) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = await client.list_tools()
    names_and_descriptions = {(t.name, t.description) for t in tools.tools}
    assert names_and_descriptions == {
        ("send_turn", "Envia lo que dice el cliente al kiosco."),
        ("send_confirmation", "Confirma o rechaza el resumen que propuso el kiosco."),
        ("send_identification", "Proporciona el numero de CI del cliente."),
    }


async def test_a_tool_call_forwards_arguments_to_the_real_session_method() -> None:
    session = FakeSession()
    async with serve_kiosk_tools(session) as url:
        async with streamable_http_client(url) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                result = await client.call_tool(
                    "send_turn", {"transcript": "hola", "is_clarification": True}
                )
    assert session.calls == [("send_turn", "hola", True)]
    assert result.content[0].text == "next_action=CONFIRM"


async def test_call_results_stay_clean_under_the_turn_budget() -> None:
    session = FakeSession()
    async with serve_kiosk_tools(session) as url:
        async with streamable_http_client(url) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                texts = []
                for _ in range(MAX_TOOL_CALLS):
                    result = await client.call_tool(
                        "send_turn", {"transcript": "x", "is_clarification": False}
                    )
                    texts.append(result.content[0].text)
    assert all("TERMINATE" not in text for text in texts)


async def test_a_call_past_the_turn_budget_carries_a_hard_stop_instruction() -> None:
    """Mirrors `ConversationSession._describe()`'s own `self.finished` messaging pattern:
    a CLI-driven customer has no AutoGen termination hook to catch, so the stop signal has
    to travel inside the tool result text itself."""
    session = FakeSession()
    async with serve_kiosk_tools(session) as url:
        async with streamable_http_client(url) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                for _ in range(MAX_TOOL_CALLS):
                    await client.call_tool(
                        "send_turn", {"transcript": "x", "is_clarification": False}
                    )
                over_budget = await client.call_tool(
                    "send_turn", {"transcript": "x", "is_clarification": False}
                )
    assert "TERMINATE" in over_budget.content[0].text


async def test_the_yielded_url_is_a_working_localhost_streamable_http_endpoint() -> None:
    session = FakeSession()
    async with serve_kiosk_tools(session) as url:
        assert url.startswith("http://127.0.0.1:")
        assert url.endswith("/mcp")
