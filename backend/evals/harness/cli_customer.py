"""Simulated-customer backends that drive a live kiosk session through a local CLI
(`claude -p` / `codex exec`) instead of AutoGen's native OpenAI tool-calling.

Neither CLI accepts arbitrary caller-defined tools as a request parameter the way the
OpenAI Chat Completions API does, but both already run a full agentic tool-calling loop
in their non-interactive mode, and both can be pointed at an MCP server for tools they
weren't shipped with. `mcp_kiosk_server.serve_kiosk_tools` stands up exactly that --
`send_turn`/`send_confirmation`/`send_identification`, the same 3 bound methods AutoGen
already calls today -- for the one scenario's duration; this module wires each CLI at
that server and lets its own loop drive the session, exactly as `AssistantAgent` does
today, over MCP instead of native tool-calling.

Neither backend returns anything: `session` (a `ConversationSession`) is mutated in place
by the MCP tool calls the CLI makes, the same contract the AutoGen path already has --
`runner.py` reads `session`'s transcript afterward either way.
"""

import json
import tempfile
from typing import Protocol

from harness.agent import build_system_message
from harness.cli_subprocess import run_cli
from harness.scenarios.models import Scenario
from harness.session import ConversationSession


class CliCustomerBackend(Protocol):
    async def run(
        self,
        *,
        scenario: Scenario,
        session: ConversationSession,
        mcp_url: str,
        initial_task: str,
        timeout_seconds: float,
    ) -> None: ...


_KIOSK_MCP_TOOLS = (
    "mcp__kiosk__send_turn,mcp__kiosk__send_confirmation,mcp__kiosk__send_identification"
)


class ClaudeCodeCustomerBackend:
    """Runs `claude -p` pointed at the scenario's kiosk MCP server.

    Confirmed live, in this order:
    - `--safe-mode` disables MCP servers wholesale (it's in the flag's own `--help`
      text: "...MCP servers..." among what it turns off) -- the judge could use it (no
      MCP involved there) but the customer can't. `--setting-sources ""` is the
      substitute: excludes project/user/local settings (hooks, permission defaults, this
      repo's own CLAUDE.md) without touching the MCP server passed explicitly via
      `--mcp-config`, which isn't a "setting source".
    - `--tools` allowlists only the 3 kiosk tools by their MCP-derived names
      (`mcp__<server-name>__<tool-name>`, matching the server name
      `serve_kiosk_tools` registers) -- confirmed correct by the model actually
      attempting exactly these names once visible. Claude Code exposes nothing else, no
      bash/file/web access.
    - `--tools` alone isn't enough to let a `-p` (non-interactive) session actually
      execute an MCP tool call: it still hit the permission gate and was denied 3 times
      with no prompt to approve (no TTY to ask). `--allowedTools` pre-authorizes the same
      3 names for that gate. Safe to pre-authorize broadly here since `--tools` has
      already restricted what's reachable to just these 3 kiosk calls.

    `DEFAULT_MODEL`/`--effort low` mirror the OpenAI customer's own default
    (`gpt-5.4-mini`, `reasoning_effort="none"` in `runner.py`) -- role-play plus picking
    one of 3 tools against an explicit `next_action` doesn't need deep reasoning, on any
    provider. Confirmed live: `haiku` + `--effort low` correctly drove the session (used
    `claude-haiku-4-5` exclusively, no escalation to a bigger model) at a fraction of the
    cost and latency of the CLI's own default (`claude-sonnet-5`). Effort is forced by
    *role*, not left to whatever model is chosen -- same as the OpenAI customer, which
    forces `reasoning_effort="none"` regardless of which `--model` was passed.
    `underlying_model` (from `--model claude-code:<alias>`) overrides `DEFAULT_MODEL`
    only, never the effort.
    """

    DEFAULT_MODEL = "haiku"

    def __init__(self, underlying_model: str | None = None) -> None:
        self.underlying_model = underlying_model

    async def run(
        self,
        *,
        scenario: Scenario,
        session: ConversationSession,
        mcp_url: str,
        initial_task: str,
        timeout_seconds: float,
    ) -> None:
        mcp_config = json.dumps({"mcpServers": {"kiosk": {"type": "http", "url": mcp_url}}})
        args = [
            "claude",
            "-p",
            "--mcp-config",
            mcp_config,
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--tools",
            _KIOSK_MCP_TOOLS,
            "--allowedTools",
            _KIOSK_MCP_TOOLS,
            "--no-session-persistence",
            "--model",
            self.underlying_model or self.DEFAULT_MODEL,
            "--effort",
            "low",
            "--system-prompt",
            build_system_message(scenario),
        ]
        await run_cli(*args, stdin=initial_task, timeout_seconds=timeout_seconds, label="claude")


class CodexCustomerBackend:
    """Runs `codex exec` pointed at the scenario's kiosk MCP server via the `-c` ephemeral
    config-override mechanism (`codex mcp add --url` is codex's *persistent* form; `-c
    mcp_servers.kiosk.url=...` is its one-invocation equivalent, matching
    `--ignore-user-config`'s isolation already used for the judge).

    Confirmed live: codex gates MCP tool calls behind its own approval policy, same as
    Claude's permission gate -- with no flag set the call came back
    `error: "user cancelled MCP tool call"` every time, with nothing to approve it
    non-interactively (`-s read-only` alone, and `-c approval_policy="never"` on top of
    it, both left the gate in place). `--approve-for-me` is what actually auto-approves
    it -- but it's mutually exclusive with `-s`/`--sandbox` (codex rejects the
    combination outright) and implies `workspace-write` on its own, a real step down
    from `read-only`'s isolation. codex also has no per-tool allowlist like Claude's
    `--tools`, so its own built-in shell tool stays nominally reachable even though the
    system prompt never mentions it. `-C <scratch>` (a fresh, empty temp directory,
    thrown away after) is the mitigation: if the model ever did reach for its own tools
    instead of the kiosk MCP ones, `workspace-write` can only reach that empty directory,
    never this repository.

    Codex `exec` has no `--system-prompt` flag, so the system message is prepended to the
    piped stdin prompt instead -- same pattern already used for the judge.

    `DEFAULT_MODEL`/`model_reasoning_effort="low"` mirror the OpenAI customer's own
    default (`gpt-5.4-mini`, `reasoning_effort="none"` in `runner.py`) for the same
    reason as the Claude backend: role-play plus picking one of 3 tools doesn't need
    deep reasoning. `gpt-5.4-mini` is confirmed available on this account (`codex debug
    models`) and is the exact same model the OpenAI customer already defaults to --
    confirmed live with `model_reasoning_effort="low"` (its own catalog entry lists
    `low` as a supported level) driving the kiosk session correctly. Effort is forced by
    role regardless of `underlying_model`, same as the Claude backend.
    """

    DEFAULT_MODEL = "gpt-5.4-mini"

    def __init__(self, underlying_model: str | None = None) -> None:
        self.underlying_model = underlying_model

    async def run(
        self,
        *,
        scenario: Scenario,
        session: ConversationSession,
        mcp_url: str,
        initial_task: str,
        timeout_seconds: float,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="kiosk-eval-codex-customer-") as scratch:
            args = [
                "codex",
                "exec",
                "-c",
                f'mcp_servers.kiosk.url="{mcp_url}"',
                "-c",
                'model_reasoning_effort="low"',
                "-m",
                self.underlying_model or self.DEFAULT_MODEL,
                "--approve-for-me",
                "--skip-git-repo-check",
                "--ephemeral",
                "--ignore-user-config",
                "-C",
                scratch,
            ]
            stdin = f"{build_system_message(scenario)}\n\n{initial_task}"
            await run_cli(*args, stdin=stdin, timeout_seconds=timeout_seconds, label="codex")


def build_cli_customer_backend(provider: str, underlying_model: str | None) -> CliCustomerBackend:
    if provider == "claude-code":
        return ClaudeCodeCustomerBackend(underlying_model)
    if provider == "codex":
        return CodexCustomerBackend(underlying_model)
    raise ValueError(f"unknown CLI customer provider: {provider!r}")
