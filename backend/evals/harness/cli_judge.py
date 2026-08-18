"""Judge backends that run a local coding-agent CLI instead of calling an LLM API.

`Judge` (see `judge.py`) needs one thing from whichever provider it is pointed at: hand it
a system message plus a dossier, get back JSON matching `JudgeVerdict`'s schema. The
Chat Completions path gets that through AutoGen's `AssistantAgent` +
`output_content_type`. These two backends get the same result from a local CLI's own
non-interactive, JSON-schema-constrained mode -- `claude -p` and `codex exec` -- so the
judge is scored under whatever plan/login that CLI already has, instead of
`OPENAI_API_KEY`.

Both CLIs are full coding-agent harnesses with their own built-in tools (bash, file edits,
web), which is exactly what the judge must NOT have: it only ever reads a dossier and
writes a verdict, and giving it shell access would be a pointless blast-radius increase
for a scoring call. Every flag below is chosen to turn that off, and to stop either CLI
from picking up this repository's own `CLAUDE.md` / `AGENTS.md` / project config, which
would otherwise leak unrelated instructions into a call that must only follow
`JUDGE_SYSTEM_MESSAGE`.

Both backends only ever raise -- they never return a `JudgeVerdict` themselves. `Judge.assess`
already retries twice and falls back to `JudgeVerdict.unavailable(...)` on any exception
(a hung process, a non-zero exit, output that isn't the requested JSON); reusing that path
here means a broken CLI invocation degrades exactly like a broken API call already does,
rather than needing its own failure handling.
"""

import json
import tempfile
from pathlib import Path
from typing import Protocol

from harness.cli_subprocess import CliError, run_cli

# `run_cli` is now shared with `cli_customer.py` (see cli_subprocess.py); kept as module
# attributes here under their original names so existing call sites and tests --
# `patch("harness.cli_judge._run", ...)` -- keep working unchanged.
CliJudgeError = CliError
_run = run_cli


class CliJudgeBackend(Protocol):
    async def score(
        self, *, system_message: str, dossier: str, schema: dict, timeout_seconds: float
    ) -> str:
        """Returns the raw JSON text the CLI produced -- not yet validated against
        `JudgeVerdict`; that happens once, in `judge.py`, the same place it already
        happens for the OpenAI path."""
        ...


class ClaudeCodeJudgeBackend:
    """Runs `claude -p` with a JSON Schema the CLI enforces natively -- no "reply with
    only JSON" prompt-begging needed. `--safe-mode` is what keeps this repo's own
    `CLAUDE.md`, hooks, plugins and memory files out of a call that must only follow the
    judge's own system prompt; `--tools ""` removes the built-in tools the judge has no
    use for.

    Deliberately `--safe-mode`, not `--bare`: `--bare` disables OAuth/keychain auth and
    requires `ANTHROPIC_API_KEY` (confirmed against `claude --help`), which breaks on a
    subscription login (`claude.ai` OAuth, no API key set) -- the common case, and this
    machine's own setup. `--safe-mode` gets the same "don't load repo/user
    customizations" isolation without touching how the CLI authenticates.
    """

    def __init__(self, underlying_model: str | None = None) -> None:
        self.underlying_model = underlying_model

    async def score(
        self, *, system_message: str, dossier: str, schema: dict, timeout_seconds: float
    ) -> str:
        args = [
            "claude",
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema),
            "--system-prompt",
            system_message,
            "--safe-mode",
            "--tools",
            "",
            "--strict-mcp-config",
            "--no-session-persistence",
        ]
        if self.underlying_model:
            args += ["--model", self.underlying_model]
        raw = await _run(*args, stdin=dossier, timeout_seconds=timeout_seconds, label="claude")
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CliJudgeError(f"claude did not return JSON: {raw[:500]}") from exc
        # `--output-format json` wraps the model's final answer in an envelope alongside
        # session metadata (cost, duration, session id). Confirmed live: the envelope
        # carries the schema-validated answer twice -- as a parsed object under
        # `structured_output`, and as its JSON-text form under `result`. Prefer the
        # parsed one (no re-parse needed downstream); fall back through `result`, then
        # the raw envelope, so a future CLI reshaping this surfaces as a JudgeVerdict
        # validation error (readable) rather than a KeyError (not).
        if isinstance(envelope, dict) and envelope.get("structured_output") is not None:
            result = envelope["structured_output"]
        elif isinstance(envelope, dict):
            result = envelope.get("result", envelope)
        else:
            result = envelope
        return result if isinstance(result, str) else json.dumps(result)


def _make_openai_strict_schema(schema: dict) -> dict:
    """Codex's `--output-schema` goes straight to OpenAI's strict Structured Outputs mode
    server-side, which imposes two constraints Pydantic's `model_json_schema()` does not
    meet on its own -- both confirmed live against a real `codex exec 400`:

    1. Every object needs an explicit `additionalProperties: false`
       (`invalid_json_schema`: `"'additionalProperties' is required to be supplied and to
       be false"`).
    2. Every object's `required` array must list *every* key in its `properties`, not
       just the ones without a Pydantic default (`invalid_json_schema`: `"'required' is
       required to be supplied and to be an array including every key in properties.
       Missing 'failures'."` -- `JudgeVerdict.failures`/`.strengths` have
       `default_factory=list`, so Pydantic omits them from `required`).

    Both apply to every object in the schema, not just the top-level one -- `JudgeVerdict`
    nests `DimensionScore` five times via `$defs`/`$ref` -- so this walks `properties`,
    `$defs`/`definitions`, `items`, and `anyOf`/`allOf`/`oneOf` recursively. Forcing a
    Pydantic-optional field into the wire-level `required` doesn't change what
    `JudgeVerdict.model_validate_json()` accepts afterwards -- `failures: []` still
    satisfies `Field(default_factory=list)` -- it only means the model must always emit
    the key, which structured output already tends to do anyway.
    """

    def walk(node: object) -> object:
        if isinstance(node, dict):
            fixed = {key: walk(value) for key, value in node.items()}
            if fixed.get("type") == "object" or "properties" in fixed:
                fixed.setdefault("additionalProperties", False)
                if "properties" in fixed:
                    fixed["required"] = list(fixed["properties"].keys())
            return fixed
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(schema)  # type: ignore[return-value]


class CodexJudgeBackend:
    """Runs `codex exec` with `--output-schema` (a file, unlike Claude's inline
    `--json-schema`) and reads the verdict back from `--output-last-message`.
    `-s read-only --ephemeral --skip-git-repo-check --ignore-user-config` is Codex's
    equivalent of `--safe-mode`: no file writes, nothing persisted, no repo-local config
    picked up. Codex's `exec` has no `--system-prompt` flag, so the system message is
    prepended to the piped prompt instead.
    """

    def __init__(self, underlying_model: str | None = None) -> None:
        self.underlying_model = underlying_model

    async def score(
        self, *, system_message: str, dossier: str, schema: dict, timeout_seconds: float
    ) -> str:
        with tempfile.TemporaryDirectory(prefix="kiosk-eval-codex-") as scratch:
            schema_path = Path(scratch) / "schema.json"
            output_path = Path(scratch) / "verdict.txt"
            schema_path.write_text(json.dumps(_make_openai_strict_schema(schema)), encoding="utf-8")

            args = [
                "codex",
                "exec",
                "--json",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "-s",
                "read-only",
                "--skip-git-repo-check",
                "--ephemeral",
                "--ignore-user-config",
                "-C",
                scratch,
            ]
            if self.underlying_model:
                args += ["-m", self.underlying_model]
            await _run(
                *args,
                stdin=f"{system_message}\n\n{dossier}",
                timeout_seconds=timeout_seconds,
                label="codex",
            )
            if not output_path.exists():
                raise CliJudgeError("codex exited 0 but wrote no --output-last-message file")
            return output_path.read_text(encoding="utf-8")


def build_cli_judge_backend(provider: str, underlying_model: str | None) -> CliJudgeBackend:
    if provider == "claude-code":
        return ClaudeCodeJudgeBackend(underlying_model)
    if provider == "codex":
        return CodexJudgeBackend(underlying_model)
    raise ValueError(f"unknown CLI judge provider: {provider!r}")
