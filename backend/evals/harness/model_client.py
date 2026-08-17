"""Builds the OpenAI model clients the customer agent and the judge use, and resolves
which provider a `--model`/`--judge-model` string points at.

`OpenAIChatCompletionClient` looks the model name up in a table baked into the installed
`autogen-ext`, and raises `ValueError: model_info is required when model name is not a
valid OpenAI model` for anything it does not recognise. That table only moves when the
package is upgraded, so a model newer than the pinned release -- including
`ORCHESTRATION_MODEL` from `backend/.env` -- would fail at construction time, before a
single request is made.

Rather than pin the harness to whatever OpenAI models `autogen-ext` happened to know
about at release, unrecognised names get an explicit `model_info` describing the
capabilities the harness actually depends on: tool calling for the customer agent's three
tools, and structured output for the judge's verdict schema. If a name is passed that
truly lacks them, the failure surfaces as an API error on the first call, with the model
name in it -- which is a far more useful signal than a constructor rejecting the name.
"""

from typing import Literal

from autogen_core.models import ModelFamily, ModelInfo
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.models.openai import _model_info as autogen_model_info

CliProvider = Literal["claude-code", "codex"]

# `--model`/`--judge-model` stay a single string -- no new CLI flag -- so a CLI-backed
# judge is selected by a sentinel prefix instead of a model name AutoGen would recognise:
# "claude-code" / "codex" (that provider's own default model) or "claude-code:opus" /
# "codex:gpt-5.2-codex" (an explicit underlying model). Anything else is unchanged and
# goes to build_model_client() below, exactly as before this existed.
_CLI_PROVIDERS: tuple[CliProvider, ...] = ("claude-code", "codex")


def resolve_provider(model: str) -> tuple[CliProvider | None, str | None]:
    """Splits a `--model`/`--judge-model` string into `(provider, underlying_model)`.

    `(None, None)` means "not a CLI sentinel -- use the OpenAI path via
    `build_model_client()`", which is every model name that predates this function.
    """
    prefix, _, rest = model.partition(":")
    if prefix not in _CLI_PROVIDERS:
        return None, None
    return prefix, (rest or None)  # type: ignore[return-value]


FALLBACK_MODEL_INFO = ModelInfo(
    vision=True,
    function_calling=True,
    json_output=True,
    structured_output=True,
    family=ModelFamily.UNKNOWN,
)


def is_known_to_autogen(model: str) -> bool:
    resolved = autogen_model_info.resolve_model(model)
    return resolved in autogen_model_info._MODEL_INFO


def build_model_client(model: str, **create_args) -> OpenAIChatCompletionClient:
    """`**create_args` (e.g. `reasoning_effort`, `verbosity`, `prompt_cache_key`) are
    forwarded to every completion this client makes. Unknown or unsupported keys are
    filtered by `autogen_ext`'s own `_create_args_from_config` before the request goes
    out, so passing a parameter the pinned SDK does not recognise is a no-op rather than
    a crash -- it just costs nothing to try."""
    if is_known_to_autogen(model):
        return OpenAIChatCompletionClient(model=model, **create_args)
    return OpenAIChatCompletionClient(model=model, model_info=FALLBACK_MODEL_INFO, **create_args)
