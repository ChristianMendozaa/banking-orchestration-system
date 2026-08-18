"""In-process MCP servers exposing the same 3 kiosk tools the AutoGen customer agent
already calls -- `send_turn`, `send_confirmation`, `send_identification` on
`ConversationSession` (see `session.py`) -- so a local CLI (`claude -p` / `codex exec`)
can drive the same live session over MCP instead of the OpenAI Chat Completions API's
native tool-calling.

Localhost-only, no auth -- the only thing that can ever reach these ports is the CLI
subprocess the harness itself just spawned, on the same machine, for the few minutes one
scenario takes -- unlike `backend/app/mcp_server` (this repo's production MCP server).

Two entry points:

- `serve_kiosk_tools(session)`: one server bound to one fixed session, torn down after.
  Simple and correct for a single, one-shot connection (this is what
  `tests/test_mcp_kiosk_server.py` exercises directly against a real MCP client).
- `serve_kiosk_pool(size)`: `size` long-lived servers, reused across every scenario in a
  run rather than rebuilt per scenario. `runner.py` uses this one for the actual CLI
  customer backends -- see its docstring below for why a fresh server per scenario
  doesn't work in practice.
"""

import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass

import uvicorn
from mcp.server.mcpserver import MCPServer

from harness.session import ConversationSession

# Matches AutoGen's `max_tool_iterations=12` on the same customer agent (agent.py) -- the
# turn budget is a property of the *scenario*, not of which provider is driving it.
MAX_TOOL_CALLS = 12

STOP_INSTRUCTION = (
    "\n\nHas alcanzado el limite de turnos para esta sesion. No llames mas herramientas; "
    "responde exactamente TERMINATE."
)

# How long to wait for uvicorn to bind before giving up -- generous for a localhost
# ASGI server that has no network or disk I/O to do before it's ready.
STARTUP_TIMEOUT_SECONDS = 5.0


def _free_port() -> int:
    """Bind to port 0 to let the OS pick a free one, then release it immediately -- the
    same pattern test fixtures (e.g. pytest-asyncio's own) use for an ephemeral local
    server. `run_streamable_http_async` takes a fixed port with no built-in "give me any
    free port and tell me which one" mode, so this has to happen a level up."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _build_server(session: ConversationSession) -> MCPServer:
    """Three tools, each a thin wrapper over the *same* bound method AutoGen already
    calls today -- `@mcp.tool`'s description is the method's own Spanish docstring,
    reused verbatim rather than duplicated as separate prompt text to maintain in sync."""
    mcp = MCPServer(name="kiosk-eval-customer-tools")
    calls = 0

    def budget_suffix() -> str:
        nonlocal calls
        calls += 1
        return STOP_INSTRUCTION if calls > MAX_TOOL_CALLS else ""

    @mcp.tool(description=(session.send_turn.__doc__ or "").strip())
    async def send_turn(transcript: str, is_clarification: bool) -> str:
        return await session.send_turn(transcript, is_clarification) + budget_suffix()

    @mcp.tool(description=(session.send_confirmation.__doc__ or "").strip())
    async def send_confirmation(confirmed: bool) -> str:
        return await session.send_confirmation(confirmed) + budget_suffix()

    @mcp.tool(description=(session.send_identification.__doc__ or "").strip())
    async def send_identification(identifier: str) -> str:
        return await session.send_identification(identifier) + budget_suffix()

    return mcp


async def _await_started(uv_server: uvicorn.Server, serve_task: asyncio.Task) -> None:
    deadline = asyncio.get_running_loop().time() + STARTUP_TIMEOUT_SECONDS
    while not uv_server.started:
        if serve_task.done():
            serve_task.result()  # re-raise whatever failed startup, immediately
        if asyncio.get_running_loop().time() > deadline:
            raise RuntimeError(f"kiosk MCP server did not start within {STARTUP_TIMEOUT_SECONDS}s")
        await asyncio.sleep(0.01)


async def _shutdown(uv_server: uvicorn.Server, serve_task: asyncio.Task) -> None:
    # Ask uvicorn to shut down on its own turn first -- cancelling the task outright
    # interrupts it mid-lifespan-protocol and prints a harmless but noisy CancelledError
    # traceback on every scenario. Only force it if it doesn't.
    uv_server.should_exit = True
    try:
        await asyncio.wait_for(serve_task, timeout=2.0)
    except (TimeoutError, asyncio.CancelledError):
        serve_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await serve_task


@contextlib.asynccontextmanager
async def serve_kiosk_tools(session: ConversationSession) -> AsyncIterator[str]:
    """Starts the MCP server as a background task, yields its URL once uvicorn has
    actually bound the socket, and tears it down on exit.

    `MCPServer.run_streamable_http_async` (the SDK's own convenience wrapper) blocks
    until shutdown and gives no way to know when the server is actually ready to accept
    connections, so this drives `uvicorn.Server` directly -- same internals, but keeping
    the `Server` object lets the loop poll `.started` before handing the URL to a caller
    that's about to spawn a CLI subprocess expecting it to already be listening.
    """
    server = _build_server(session)
    port = _free_port()
    app = server.streamable_http_app(host="127.0.0.1")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    uv_server = uvicorn.Server(config)
    serve_task = asyncio.create_task(uv_server.serve())
    try:
        await _await_started(uv_server, serve_task)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        await _shutdown(uv_server, serve_task)


@dataclass(slots=True)
class SessionHolder:
    """Mutable pointer to the `ConversationSession` a pooled server's tools currently
    operate on. `_build_pooled_server`'s closures read `.session` at call time instead of
    closing over one fixed session, so the same live server (same port, same uvicorn/ASGI
    app instance) can be handed to a new scenario without ever being torn down and
    rebuilt. `calls` is the tool-call budget counter -- also per-holder, reset on every
    `bind()`, since the budget is a property of the *scenario* currently using the slot,
    not of the server object itself."""

    session: ConversationSession | None = None
    calls: int = 0

    def bind(self, session: ConversationSession) -> None:
        self.session = session
        self.calls = 0

    def release(self) -> None:
        self.session = None


def _build_pooled_server(holder: SessionHolder) -> MCPServer:
    """Same 3 tools as `_build_server`, reading the active session from `holder` at call
    time. Descriptions come from the `ConversationSession` class directly rather than an
    instance -- there is no session bound to the holder until a scenario acquires this
    server -- which is fine because a method's docstring does not vary by instance."""
    mcp = MCPServer(name="kiosk-eval-customer-tools")

    def budget_suffix() -> str:
        holder.calls += 1
        return STOP_INSTRUCTION if holder.calls > MAX_TOOL_CALLS else ""

    def active_session() -> ConversationSession:
        if holder.session is None:
            raise RuntimeError("pooled kiosk MCP server has no session bound to it")
        return holder.session

    @mcp.tool(description=(ConversationSession.send_turn.__doc__ or "").strip())
    async def send_turn(transcript: str, is_clarification: bool) -> str:
        return await active_session().send_turn(transcript, is_clarification) + budget_suffix()

    @mcp.tool(description=(ConversationSession.send_confirmation.__doc__ or "").strip())
    async def send_confirmation(confirmed: bool) -> str:
        return await active_session().send_confirmation(confirmed) + budget_suffix()

    @mcp.tool(description=(ConversationSession.send_identification.__doc__ or "").strip())
    async def send_identification(identifier: str) -> str:
        return await active_session().send_identification(identifier) + budget_suffix()

    return mcp


@dataclass(slots=True)
class _PooledServer:
    url: str
    holder: SessionHolder
    uv_server: uvicorn.Server
    serve_task: asyncio.Task


class KioskMcpServerPool:
    """`size` long-lived kiosk MCP servers, borrowed one at a time for a scenario's
    duration and returned afterward -- never torn down and rebuilt between scenarios.
    See `serve_kiosk_pool`'s docstring for why that matters."""

    def __init__(self, servers: list[_PooledServer]) -> None:
        self._queue: asyncio.Queue[_PooledServer] = asyncio.Queue()
        for pooled in servers:
            self._queue.put_nowait(pooled)

    @contextlib.asynccontextmanager
    async def acquire(self, session: ConversationSession) -> AsyncIterator[str]:
        pooled = await self._queue.get()
        pooled.holder.bind(session)
        try:
            yield pooled.url
        finally:
            pooled.holder.release()
            self._queue.put_nowait(pooled)


async def _start_pooled_server() -> _PooledServer:
    holder = SessionHolder()
    server = _build_pooled_server(holder)
    port = _free_port()
    app = server.streamable_http_app(host="127.0.0.1")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    uv_server = uvicorn.Server(config)
    serve_task = asyncio.create_task(uv_server.serve())
    await _await_started(uv_server, serve_task)
    return _PooledServer(
        url=f"http://127.0.0.1:{port}/mcp",
        holder=holder,
        uv_server=uv_server,
        serve_task=serve_task,
    )


@contextlib.asynccontextmanager
async def serve_kiosk_pool(size: int) -> AsyncIterator[KioskMcpServerPool]:
    """Starts `size` MCP servers up front and reuses each one for every scenario that
    borrows it over the run, rather than spinning up (and tearing down) a fresh server
    per scenario the way `serve_kiosk_tools` does.

    Confirmed live: a local CLI customer (codex, and by the same client-side mechanism
    presumably claude) only completes a real MCP handshake against the *first* freshly
    bound server it ever talks to in a process. Every subsequent CLI invocation pointed
    at a brand-new server instance -- even on a different port, different server name,
    after a multi-second delay, at concurrency 1 -- fails immediately with "Request
    stream 0 not found" / "ASGI callable returned without completing response": the
    CLI's own MCP client appears to attempt a resumed/replayed connection against stream
    state that only exists on a server it has already talked to. Reusing the SAME server
    (swapping only which session its tools currently operate on, via `SessionHolder`)
    sidesteps this: confirmed live that a second, third, ... CLI invocation against an
    already-used server connects and calls tools exactly like the first. Sized to
    `--concurrency` by the caller, so every concurrent scenario slot owns one server for
    the whole run instead of creating a fresh one per scenario.
    """
    started: list[_PooledServer] = []
    try:
        for _ in range(max(1, size)):
            started.append(await _start_pooled_server())
        yield KioskMcpServerPool(started)
    finally:
        await asyncio.gather(
            *(_shutdown(pooled.uv_server, pooled.serve_task) for pooled in started)
        )
