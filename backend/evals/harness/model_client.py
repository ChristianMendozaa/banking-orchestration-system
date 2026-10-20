"""Builds the Anthropic model client the simulated customer runs on.

`AnthropicChatCompletionClient` looks the model name up in a table baked into the installed
`autogen-ext`, and raises `ValueError: model_info is required when model name is not
recognized` for anything missing from it. That table stops at the Claude 4 models, and
`autogen-ext` 0.7.5 is the last release, so the `claude-haiku-5-5` default -- or any model a
run names with `--model` -- would fail at construction time, before a single request is made.

So every client gets an explicit `model_info` describing the capabilities the customer
actually depends on: tool calling for its three kiosk tools. Structured output is declared
absent because this client raises on it for Anthropic models; the judge, which needs it,
calls the Anthropic SDK directly instead (see `judge.py`).
"""

from typing import Any

from anthropic import AsyncAnthropic
from autogen_core.models import ModelFamily, ModelInfo
from autogen_ext.models.anthropic import AnthropicChatCompletionClient

CUSTOMER_MODEL_INFO = ModelInfo(
    vision=True,
    function_calling=True,
    json_output=False,
    structured_output=False,
    family=ModelFamily.UNKNOWN,
)

# Each customer turn is one short Spanish sentence or one tool call.
CUSTOMER_MAX_TOKENS = 4096


class _MessagesWithoutSampling:
    """`autogen-ext` 0.7.5 puts `temperature` (1.0 unless configured) on every request,
    streaming or not. `anthropic` 1.x removed the sampling parameters from
    `messages.create` -- current models reject anything but their defaults -- so the call
    fails with `TypeError: unexpected keyword argument 'temperature'` before it is sent.
    1.0 is the model's own default, so dropping it changes nothing the model sees."""

    def __init__(self, messages: Any) -> None:
        self._messages = messages

    async def create(self, **request_args: Any) -> Any:
        request_args.pop("temperature", None)
        return await self._messages.create(**request_args)


class _ClientWithoutSampling:
    """Everything AutoGen reaches for on its SDK client except `messages` is passed through."""

    def __init__(self, client: AsyncAnthropic) -> None:
        self._client = client
        self.messages = _MessagesWithoutSampling(client.messages)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def build_customer_client(model: str) -> AnthropicChatCompletionClient:
    """Thinking is off. The customer is role-play plus picking one of three tools against an
    explicit next_action instruction -- it does not need deep reasoning, and a customer that
    reasons less is also less likely to second-guess its way off the persona's script.
    It is also the one setting this client handles correctly: it does not send thinking
    blocks back with tool results, which an adaptive-thinking conversation expects, and it
    does not forward `output_config`, so effort stays at the model's default either way.

    `{"type": "disabled"}` is accepted by Claude Haiku 5.5 at its default effort, but is a
    400 on Claude Sonnet 5.5 and Claude Opus 5.5 -- the customer is meant to stay on Haiku.
    """
    client = AnthropicChatCompletionClient(
        model=model,
        model_info=CUSTOMER_MODEL_INFO,
        max_tokens=CUSTOMER_MAX_TOKENS,
        thinking={"type": "disabled"},
    )
    client._client = _ClientWithoutSampling(client._client)
    return client
