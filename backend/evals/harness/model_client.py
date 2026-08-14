"""Builds the OpenAI model clients the customer agent and the judge use.

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

from autogen_core.models import ModelFamily, ModelInfo
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.models.openai import _model_info as autogen_model_info

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


def build_model_client(model: str) -> OpenAIChatCompletionClient:
    if is_known_to_autogen(model):
        return OpenAIChatCompletionClient(model=model)
    return OpenAIChatCompletionClient(model=model, model_info=FALLBACK_MODEL_INFO)
