"""An in-process, per-scenario MCP server exposing the same 3 kiosk tools the AutoGen
customer agent already calls -- `send_turn`, `send_confirmation`, `send_identification`
on `ConversationSession` (see `session.py`) -- so a local CLI (`claude -p` / `codex exec`)
can drive the same live session over MCP instead of the OpenAI Chat Completions API's
native tool-calling.

Localhost-only, ephemeral, torn down within the same scenario's timeout -- unlike
`backend/app/mcp_server` (this repo's production MCP server), there is no auth here: the
only thing that can ever reach this port is the CLI subprocess the harness itself just
spawned, on the same machine, for the few minutes one scenario takes.
"""

import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator

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
        deadline = asyncio.get_running_loop().time() + STARTUP_TIMEOUT_SECONDS
        while not uv_server.started:
            if serve_task.done():
                serve_task.result()  # re-raise whatever failed startup, immediately
            if asyncio.get_running_loop().time() > deadline:
                raise RuntimeError(
                    f"kiosk MCP server did not start within {STARTUP_TIMEOUT_SECONDS}s"
                )
            await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        # Ask uvicorn to shut down on its own turn first -- cancelling the task outright
        # interrupts it mid-lifespan-protocol and prints a harmless but noisy
        # CancelledError traceback on every scenario. Only force it if it doesn't.
        uv_server.should_exit = True
        try:
            await asyncio.wait_for(serve_task, timeout=2.0)
        except (TimeoutError, asyncio.CancelledError):
            serve_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await serve_task
