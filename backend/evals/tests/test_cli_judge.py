"""The local-CLI judge backends (`claude-code` / `codex`).

Never spawns a real `claude`/`codex` process -- both binaries may not even be installed
wherever this suite runs, and a real call would be billed against whatever plan/login the
CLI has. `_run()` (the subprocess wrapper both backends share) is exercised against a
mocked `asyncio.create_subprocess_exec`; each backend's own `score()` is exercised against
a mocked `_run()`, so what's actually verified is argv construction and output parsing --
exactly the two things a real CLI change could silently break.
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from harness.cli_judge import (
    ClaudeCodeJudgeBackend,
    CliJudgeError,
    CodexJudgeBackend,
    _make_openai_strict_schema,
    _run,
)

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

NESTED_SCHEMA = {
    "$defs": {
        "Inner": {
            "type": "object",
            "properties": {"score": {"type": "integer"}},
            "required": ["score"],
        }
    },
    "type": "object",
    "properties": {"inner": {"$ref": "#/$defs/Inner"}},
    "required": ["inner"],
}


class _FakeProcess:
    def __init__(self, stdout: bytes, stderr: bytes, returncode: int, hang: bool = False):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._hang = hang
        self.killed = False

    async def communicate(self, _input: bytes | None = None) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.sleep(10)
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> None:
        return None


# --- _run: the shared subprocess wrapper ---------------------------------------------


async def test_run_returns_stdout_on_a_clean_exit() -> None:
    process = _FakeProcess(b"hello\n", b"", 0)
    with patch.object(asyncio, "create_subprocess_exec", AsyncMock(return_value=process)):
        result = await _run("echo", "hi", stdin=None, timeout_seconds=5, label="test")
    assert result == "hello\n"


async def test_run_raises_with_stderr_on_a_nonzero_exit() -> None:
    process = _FakeProcess(b"", b"boom: bad flag", 2)
    with patch.object(asyncio, "create_subprocess_exec", AsyncMock(return_value=process)):
        with pytest.raises(CliJudgeError, match="boom: bad flag"):
            await _run("claude", stdin=None, timeout_seconds=5, label="claude")


async def test_run_kills_the_process_and_raises_on_timeout() -> None:
    process = _FakeProcess(b"", b"", 0, hang=True)
    with patch.object(asyncio, "create_subprocess_exec", AsyncMock(return_value=process)):
        with pytest.raises(CliJudgeError, match="timed out"):
            await _run("claude", stdin=None, timeout_seconds=0.01, label="claude")
    assert process.killed


async def test_run_writes_stdin_when_given() -> None:
    process = _FakeProcess(b"ok", b"", 0)
    process.communicate = AsyncMock(return_value=(b"ok", b""))  # type: ignore[method-assign]
    with patch.object(asyncio, "create_subprocess_exec", AsyncMock(return_value=process)):
        await _run("claude", stdin="the dossier", timeout_seconds=5, label="claude")
    process.communicate.assert_awaited_once_with(b"the dossier")


# --- ClaudeCodeJudgeBackend -----------------------------------------------------------


async def test_claude_code_backend_passes_the_schema_and_system_prompt_as_flags() -> None:
    run = AsyncMock(return_value=json.dumps({"result": '{"ok": true}'}))
    with patch("harness.cli_judge._run", run):
        result = await ClaudeCodeJudgeBackend().score(
            system_message="You are the judge.",
            dossier="the dossier",
            schema=SCHEMA,
            timeout_seconds=5,
        )
    assert result == '{"ok": true}'
    args = run.call_args.args
    assert args[0] == "claude"
    assert "--json-schema" in args
    assert json.dumps(SCHEMA) in args
    assert "--system-prompt" in args
    assert "You are the judge." in args
    assert "--safe-mode" in args
    assert run.call_args.kwargs["stdin"] == "the dossier"


async def test_claude_code_backend_forwards_an_explicit_underlying_model() -> None:
    run = AsyncMock(return_value=json.dumps({"result": "{}"}))
    with patch("harness.cli_judge._run", run):
        await ClaudeCodeJudgeBackend(underlying_model="opus").score(
            system_message="sys", dossier="d", schema=SCHEMA, timeout_seconds=5
        )
    args = run.call_args.args
    assert args[args.index("--model") + 1] == "opus"


async def test_claude_code_backend_prefers_the_parsed_structured_output_field() -> None:
    """Confirmed live: `--output-format json` carries the schema-validated answer twice --
    parsed under `structured_output` and as JSON text under `result`. The parsed one is
    preferred so nothing downstream double-parses it."""
    envelope = {"structured_output": {"ok": True}, "result": '{"ok": true}'}
    run = AsyncMock(return_value=json.dumps(envelope))
    with patch("harness.cli_judge._run", run):
        result = await ClaudeCodeJudgeBackend().score(
            system_message="sys", dossier="d", schema=SCHEMA, timeout_seconds=5
        )
    assert json.loads(result) == {"ok": True}


async def test_claude_code_backend_falls_back_to_the_raw_envelope_if_unwrapped() -> None:
    """A future CLI version reshaping the --output-format json envelope should surface as
    a JudgeVerdict validation error upstream (readable), not a KeyError here (not)."""
    run = AsyncMock(return_value=json.dumps({"ok": True}))
    with patch("harness.cli_judge._run", run):
        result = await ClaudeCodeJudgeBackend().score(
            system_message="sys", dossier="d", schema=SCHEMA, timeout_seconds=5
        )
    assert json.loads(result) == {"ok": True}


async def test_claude_code_backend_rejects_output_that_is_not_json() -> None:
    run = AsyncMock(return_value="not json at all")
    with patch("harness.cli_judge._run", run):
        with pytest.raises(CliJudgeError, match="did not return JSON"):
            await ClaudeCodeJudgeBackend().score(
                system_message="sys", dossier="d", schema=SCHEMA, timeout_seconds=5
            )


# --- schema strictification (codex exec's OpenAI-strict Structured Outputs mode) -----
#
# Both constraints below were found by running the real thing against a real `codex
# exec`, not read off documentation: a schema missing either one 400s with
# `invalid_json_schema` and the exact field name that's wrong.


def test_strict_schema_patches_the_top_level_object() -> None:
    fixed = _make_openai_strict_schema(SCHEMA)
    assert fixed["additionalProperties"] is False


def test_strict_schema_patches_nested_defs_too() -> None:
    """codex exec 400s (invalid_json_schema) if even one nested object -- like
    JudgeVerdict's five DimensionScore fields, reached via $defs/$ref -- lacks this, not
    just the schema's root."""
    fixed = _make_openai_strict_schema(NESTED_SCHEMA)
    assert fixed["additionalProperties"] is False
    assert fixed["$defs"]["Inner"]["additionalProperties"] is False


def test_strict_schema_requires_every_property_key_not_just_the_mandatory_ones() -> None:
    """codex exec 400s (invalid_json_schema, `"Missing 'failures'"`) on a `required` that
    only lists properties without a Pydantic default -- OpenAI's strict Structured
    Outputs mode requires every key in `properties` to also appear in `required`,
    Pydantic-optional or not."""
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        "required": ["a"],
    }
    assert _make_openai_strict_schema(schema)["required"] == ["a", "b"]


def test_strict_schema_leaves_an_explicit_additional_properties_value_alone() -> None:
    schema = {"type": "object", "properties": {}, "additionalProperties": True}
    assert _make_openai_strict_schema(schema)["additionalProperties"] is True


def test_the_judge_verdict_schema_is_codex_strict_after_patching() -> None:
    """The actual schema the harness sends, not a stand-in -- this is the one that broke
    against a real codex exec call before this fix: missing additionalProperties on both
    the root object and the nested DimensionScore under $defs, and missing
    failures/strengths from `required` (both have a Pydantic default, so model_json_schema
    omits them)."""
    from harness.judge import JudgeVerdict

    fixed = _make_openai_strict_schema(JudgeVerdict.model_json_schema())
    assert fixed["additionalProperties"] is False
    assert fixed["$defs"]["DimensionScore"]["additionalProperties"] is False
    assert set(fixed["required"]) == set(fixed["properties"])
    assert "failures" in fixed["required"]
    assert "strengths" in fixed["required"]


# --- CodexJudgeBackend -----------------------------------------------------------------


def _write_output_file(captured: dict) -> object:
    """Stands in for `codex exec` actually writing --output-last-message: real codex
    writes the file as a side effect and exits, it doesn't hand the content back on
    stdout, so the fake here does the same -- write to the path codex was told to use.

    Everything the test needs to inspect is captured *during* the call, not after: by the
    time `CodexJudgeBackend.score()` returns, its `TemporaryDirectory` has already been
    cleaned up, so the schema/output files no longer exist on disk to read back.
    """

    def side_effect(*args: str, **kwargs: object) -> str:
        captured["args"] = args
        captured["kwargs"] = kwargs
        schema_path = args[args.index("--output-schema") + 1]
        captured["schema"] = json.loads(open(schema_path, encoding="utf-8").read())
        output_path = args[args.index("--output-last-message") + 1]
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write('{"ok": true}')
        return ""

    return side_effect


async def test_codex_backend_writes_the_schema_to_a_file_and_reads_the_verdict_back() -> None:
    captured: dict = {}
    run = AsyncMock(side_effect=_write_output_file(captured))
    with patch("harness.cli_judge._run", run):
        result = await CodexJudgeBackend().score(
            system_message="You are the judge.",
            dossier="the dossier",
            schema=SCHEMA,
            timeout_seconds=5,
        )
    assert result == '{"ok": true}'
    args = captured["args"]
    assert args[0] == "codex"
    assert args[1] == "exec"
    assert captured["schema"] == {**SCHEMA, "additionalProperties": False, "required": ["ok"]}
    # No --system-prompt flag exists on `codex exec` -- the system message must instead
    # be folded into the piped stdin prompt, ahead of the dossier.
    assert "--system-prompt" not in args
    stdin = captured["kwargs"]["stdin"]
    assert stdin.startswith("You are the judge.")
    assert "the dossier" in stdin


async def test_codex_backend_forwards_an_explicit_underlying_model() -> None:
    captured: dict = {}
    run = AsyncMock(side_effect=_write_output_file(captured))
    with patch("harness.cli_judge._run", run):
        await CodexJudgeBackend(underlying_model="gpt-5.2-codex").score(
            system_message="sys", dossier="d", schema=SCHEMA, timeout_seconds=5
        )
    args = captured["args"]
    assert args[args.index("-m") + 1] == "gpt-5.2-codex"


async def test_codex_backend_raises_if_no_output_file_appears() -> None:
    """A codex version that stops honouring --output-last-message must fail loudly, not
    read stale content from a previous run or silently return an empty string."""
    run = AsyncMock(return_value="")
    with patch("harness.cli_judge._run", run):
        with pytest.raises(CliJudgeError, match="wrote no --output-last-message"):
            await CodexJudgeBackend().score(
                system_message="sys", dossier="d", schema=SCHEMA, timeout_seconds=5
            )
