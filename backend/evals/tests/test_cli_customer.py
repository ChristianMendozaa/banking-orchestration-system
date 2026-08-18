"""The local-CLI simulated-customer backends (`claude-code` / `codex`).

Never spawns a real `claude`/`codex` process or a real MCP server -- `run_cli` (shared
with `cli_judge.py`, see `cli_subprocess.py`) is mocked, so what's verified here is argv
construction and stdin content: the two things a real CLI flag change could silently
break. The MCP server itself is covered live and in `test_mcp_kiosk_server.py`; the full
live loop (a real `claude`/`codex` actually driving a real kiosk session over MCP) was
verified by hand against a running backend -- not repeatable in a hermetic suite.
"""

from unittest.mock import AsyncMock, patch

import pytest
from conftest import make_scenario

from harness.cli_customer import (
    ClaudeCodeCustomerBackend,
    CodexCustomerBackend,
    build_cli_customer_backend,
)

MCP_URL = "http://127.0.0.1:54321/mcp"


async def _run_claude(backend: ClaudeCodeCustomerBackend, **overrides):
    run = AsyncMock(return_value="")
    kwargs = {
        "scenario": make_scenario(),
        "session": object(),
        "mcp_url": MCP_URL,
        "initial_task": "Empieza a contarle al kiosco tu situacion.",
        "timeout_seconds": 300,
        **overrides,
    }
    with patch("harness.cli_customer.run_cli", run):
        await backend.run(**kwargs)
    return run


async def _run_codex(backend: CodexCustomerBackend, **overrides):
    run = AsyncMock(return_value="")
    kwargs = {
        "scenario": make_scenario(),
        "session": object(),
        "mcp_url": MCP_URL,
        "initial_task": "Empieza a contarle al kiosco tu situacion.",
        "timeout_seconds": 300,
        **overrides,
    }
    with patch("harness.cli_customer.run_cli", run):
        await backend.run(**kwargs)
    return run


# --- ClaudeCodeCustomerBackend ---------------------------------------------------------


async def test_claude_code_customer_points_the_mcp_config_at_the_given_url() -> None:
    run = await _run_claude(ClaudeCodeCustomerBackend())
    args = run.call_args.args
    assert args[0] == "claude"
    assert "-p" in args
    config = args[args.index("--mcp-config") + 1]
    assert MCP_URL in config
    assert '"type": "http"' in config or '"type":"http"' in config.replace(" ", "")


async def test_claude_code_customer_restricts_to_only_the_configured_mcp_server() -> None:
    run = await _run_claude(ClaudeCodeCustomerBackend())
    assert "--strict-mcp-config" in run.call_args.args


async def test_claude_code_customer_excludes_project_and_user_settings_not_safe_mode() -> None:
    """--safe-mode disables MCP servers wholesale (confirmed live) -- the customer must
    use --setting-sources "" instead, never --safe-mode."""
    run = await _run_claude(ClaudeCodeCustomerBackend())
    args = run.call_args.args
    assert "--safe-mode" not in args
    assert args[args.index("--setting-sources") + 1] == ""


async def test_claude_code_customer_allowlists_exactly_the_three_kiosk_tools() -> None:
    run = await _run_claude(ClaudeCodeCustomerBackend())
    args = run.call_args.args
    expected = "mcp__kiosk__send_turn,mcp__kiosk__send_confirmation,mcp__kiosk__send_identification"
    assert args[args.index("--tools") + 1] == expected


async def test_claude_code_customer_pre_authorizes_the_same_tools_for_the_permission_gate() -> None:
    """--tools alone isn't enough in non-interactive mode -- confirmed live, the call was
    denied 3 times with no prompt to approve. --allowedTools is what actually lets it
    execute."""
    run = await _run_claude(ClaudeCodeCustomerBackend())
    args = run.call_args.args
    expected = "mcp__kiosk__send_turn,mcp__kiosk__send_confirmation,mcp__kiosk__send_identification"
    assert args[args.index("--allowedTools") + 1] == expected


async def test_claude_code_customer_passes_the_scenario_system_message() -> None:
    scenario = make_scenario(goal="Te robaron la tarjeta.")
    run = await _run_claude(ClaudeCodeCustomerBackend(), scenario=scenario)
    args = run.call_args.args
    assert "Te robaron la tarjeta." in args[args.index("--system-prompt") + 1]


async def test_claude_code_customer_pipes_the_initial_task_on_stdin() -> None:
    run = await _run_claude(
        ClaudeCodeCustomerBackend(), initial_task="Empieza a contarle al kiosco tu situacion."
    )
    assert run.call_args.kwargs["stdin"] == "Empieza a contarle al kiosco tu situacion."


async def test_claude_code_customer_forwards_an_explicit_underlying_model() -> None:
    run = await _run_claude(ClaudeCodeCustomerBackend(underlying_model="opus"))
    args = run.call_args.args
    assert args[args.index("--model") + 1] == "opus"


async def test_claude_code_customer_defaults_to_haiku_when_no_alias_given() -> None:
    """Mirrors the OpenAI customer's own default (gpt-5.4-mini, not a flagship model) --
    role-play plus picking one of 3 tools doesn't need a heavyweight model. Confirmed
    live: haiku correctly drives the kiosk session, used exclusively (no escalation)."""
    run = await _run_claude(ClaudeCodeCustomerBackend())
    args = run.call_args.args
    assert args[args.index("--model") + 1] == "haiku"


async def test_claude_code_customer_forces_low_effort_regardless_of_model() -> None:
    """Effort is forced by role, not left to whatever model is chosen -- same as the
    OpenAI customer, which forces reasoning_effort="none" regardless of --model."""
    backends = (ClaudeCodeCustomerBackend(), ClaudeCodeCustomerBackend(underlying_model="opus"))
    for backend in backends:
        run = await _run_claude(backend)
        args = run.call_args.args
        assert args[args.index("--effort") + 1] == "low"


# --- CodexCustomerBackend ---------------------------------------------------------------


async def test_codex_customer_registers_the_mcp_server_via_ephemeral_override() -> None:
    run = await _run_codex(CodexCustomerBackend())
    args = run.call_args.args
    assert args[0] == "codex"
    assert args[1] == "exec"
    override = args[args.index("-c") + 1]
    assert override == f'mcp_servers.kiosk.url="{MCP_URL}"'


async def test_codex_customer_uses_approve_for_me_not_sandbox_flag() -> None:
    """-s/--sandbox is mutually exclusive with --approve-for-me (codex rejects the
    combination outright, confirmed live) -- and -s read-only alone left the MCP
    approval gate in place regardless. --approve-for-me is what actually auto-approves
    the tool call."""
    run = await _run_codex(CodexCustomerBackend())
    args = run.call_args.args
    assert "--approve-for-me" in args
    assert "-s" not in args
    assert "--sandbox" not in args


async def test_codex_customer_scopes_the_session_to_a_throwaway_directory() -> None:
    """--approve-for-me implies workspace-write -- -C points it at a fresh, empty temp
    directory so a stray shell/file tool call (codex has no per-tool allowlist like
    Claude's --tools) can't reach the repository."""
    run = await _run_codex(CodexCustomerBackend())
    args = run.call_args.args
    scratch = args[args.index("-C") + 1]
    assert "kiosk-eval-codex-customer-" in scratch


async def test_codex_customer_isolates_from_the_users_persistent_config() -> None:
    run = await _run_codex(CodexCustomerBackend())
    args = run.call_args.args
    assert "--ignore-user-config" in args
    assert "--ephemeral" in args
    assert "--skip-git-repo-check" in args


async def test_codex_customer_prepends_the_system_message_to_stdin() -> None:
    """codex exec has no --system-prompt flag -- same pattern already used for the
    judge: the system message goes ahead of the piped prompt instead."""
    scenario = make_scenario(goal="Te robaron la tarjeta.")
    run = await _run_codex(
        CodexCustomerBackend(),
        scenario=scenario,
        initial_task="Empieza a contarle al kiosco tu situacion.",
    )
    stdin = run.call_args.kwargs["stdin"]
    assert "Te robaron la tarjeta." in stdin
    assert stdin.endswith("Empieza a contarle al kiosco tu situacion.")


async def test_codex_customer_forwards_an_explicit_underlying_model() -> None:
    run = await _run_codex(CodexCustomerBackend(underlying_model="gpt-5.2-codex"))
    args = run.call_args.args
    assert args[args.index("-m") + 1] == "gpt-5.2-codex"


async def test_codex_customer_defaults_to_gpt_5_4_mini_when_no_alias_given() -> None:
    """The exact same model the OpenAI customer already defaults to, confirmed available
    on this account via `codex debug models` -- role-play plus picking one of 3 tools
    doesn't need codex's own flagship default."""
    run = await _run_codex(CodexCustomerBackend())
    args = run.call_args.args
    assert args[args.index("-m") + 1] == "gpt-5.4-mini"


async def test_codex_customer_forces_low_reasoning_effort_regardless_of_model() -> None:
    for backend in (CodexCustomerBackend(), CodexCustomerBackend(underlying_model="gpt-5.2-codex")):
        run = await _run_codex(backend)
        args = run.call_args.args
        assert 'model_reasoning_effort="low"' in args


# --- build_cli_customer_backend ---------------------------------------------------------


def test_build_cli_customer_backend_dispatches_claude_code() -> None:
    backend = build_cli_customer_backend("claude-code", None)
    assert isinstance(backend, ClaudeCodeCustomerBackend)


def test_build_cli_customer_backend_dispatches_codex() -> None:
    backend = build_cli_customer_backend("codex", "gpt-5.2-codex")
    assert isinstance(backend, CodexCustomerBackend)
    assert backend.underlying_model == "gpt-5.2-codex"


def test_build_cli_customer_backend_rejects_an_unknown_provider() -> None:
    with pytest.raises(ValueError, match="unknown CLI customer provider"):
        build_cli_customer_backend("not-a-real-provider", None)
