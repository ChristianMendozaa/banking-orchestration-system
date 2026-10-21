import time
from typing import TYPE_CHECKING

import structlog
from anthropic import AsyncAnthropic
from anthropic.types import ParsedMessage, TextBlockParam
from pydantic import BaseModel

from app.core.config import Settings
from app.domain.schemas import (
    ClassificationDecision,
    ConfirmationReading,
    GroundedAnswerDecision,
)
from app.services.prompts import (
    CLASSIFICATION_SYSTEM_PROMPT,
    CONFIRMATION_READING_SYSTEM_PROMPT,
    GROUNDED_ANSWER_SYSTEM_PROMPT,
)

if TYPE_CHECKING:
    from app.knowledge.repository import RetrievedChunk

__all__ = ["AnthropicProvider"]

logger = structlog.get_logger()

# Adaptive thinking is on by default on the orchestration model and its tokens count toward
# `max_tokens`. These ceilings are sized for the thinking a "low" effort turn spends plus the
# structured answer, not for the answer alone: a cap tuned to the JSON would stop the
# response inside the thinking block and leave nothing to parse. Grounding gets more room
# because its answer carries up to 2000 characters of text on top of the decision.
CLASSIFICATION_MAX_TOKENS = 4096
CONFIRMATION_MAX_TOKENS = 4096
GROUNDING_MAX_TOKENS = 8192


class AnthropicProvider:
    """The orchestration model: every decision the backend asks a language model for.

    Embeddings and the realtime voice channel stay on `OpenAIProvider`; Anthropic offers
    neither, and the pgvector schema is fixed to OpenAI's 1536-dimension vectors.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        api_key = settings.anthropic_api_key.get_secret_value()
        self.client = AsyncAnthropic(api_key=api_key, timeout=settings.anthropic_timeout_seconds)

    async def classify(self, masked_text: str) -> ClassificationDecision:
        # This call sits directly between the customer finishing a sentence and the kiosk
        # answering, so its latency is dead air the person hears -- on every turn, not just
        # the ones that reach the corpus. See `classification_reasoning_effort` in
        # core/config.py for why it sits at the lowest effort.
        started = time.monotonic()
        response = await self.client.messages.parse(
            model=self.settings.orchestration_model,
            max_tokens=CLASSIFICATION_MAX_TOKENS,
            system=_cached_system(CLASSIFICATION_SYSTEM_PROMPT),
            messages=[{"role": "user", "content": masked_text}],
            output_config={"effort": self.settings.classification_reasoning_effort},
            output_format=ClassificationDecision,
        )
        _log_usage("classify", response, started)
        return _parsed(response, "Claude no devolvio una clasificacion estructurada")

    async def read_confirmation(
        self, customer_summary: str, transcript: str
    ) -> ConfirmationReading:
        """What a reply to "¿me confirmas que...?" meant, when cue matching cannot say.

        Deliberately not on the hot path: `apply_confirmation` calls this only after
        `unambiguous_confirmation` returns None, so a plain "sí" still costs zero round
        trips and only the sentences that were being read wrong pay for a model.
        """
        started = time.monotonic()
        response = await self.client.messages.parse(
            model=self.settings.orchestration_model,
            max_tokens=CONFIRMATION_MAX_TOKENS,
            system=_cached_system(CONFIRMATION_READING_SYSTEM_PROMPT),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Resumen que el kiosco leyo: {customer_summary}\n"
                        f"Respuesta de la persona: {transcript}"
                    ),
                }
            ],
            # A short reading of one sentence against one summary. It sits in the same
            # blocking turn as everything else, and there is no judgement here that a step
            # of effort buys -- see `classification_reasoning_effort` in core/config.py.
            output_config={"effort": self.settings.classification_reasoning_effort},
            output_format=ConfirmationReading,
        )
        _log_usage("read_confirmation", response, started)
        return _parsed(response, "Claude no devolvio una lectura de confirmacion estructurada")

    async def grounded_answer(
        self,
        summary: str,
        chunks: list["RetrievedChunk"],
        *,
        language_feedback: str | None = None,
    ) -> GroundedAnswerDecision:
        """`language_feedback` is the reason a previous answer to this same question was
        discarded. It goes in the user turn, after the evidence, so the cached system prompt
        stays byte-identical on the retry."""
        evidence = "\n\n".join(
            f'<evidence ref="{index}" document="{item.document.title}" '
            f'page="{item.chunk.page}">\n{item.chunk.content}\n</evidence>'
            for index, item in enumerate(chunks, start=1)
        )
        started = time.monotonic()
        response = await self.client.messages.parse(
            model=self.settings.orchestration_model,
            max_tokens=GROUNDING_MAX_TOKENS,
            system=_cached_system(GROUNDED_ANSWER_SYSTEM_PROMPT),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Sucursal actual del kiosco: {self.settings.branch_name}\n"
                        f"Consulta enmascarada: {summary}\n\nEvidencia:\n{evidence}"
                        + (f"\n\n{language_feedback}" if language_feedback else "")
                    ),
                }
            ],
            # Same blocking turn as `classify`, immediately after it. This is the call that
            # decides how much of the question the evidence answers, and a wrong coverage
            # verdict reads invented banking information to a customer. See
            # `grounding_reasoning_effort` in core/config.py.
            output_config={"effort": self.settings.grounding_reasoning_effort},
            output_format=GroundedAnswerDecision,
        )
        _log_usage("grounded_answer", response, started)
        return _parsed(response, "Claude no devolvio una respuesta fundamentada estructurada")


def _cached_system(prompt: str) -> list[TextBlockParam]:
    # The system prompts are constants, so the prefix is identical on every call and the
    # cache turns most of each request's input into a cache read.
    return [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]


def _log_usage(route: str, response: ParsedMessage, started: float) -> None:
    # Per-call tokens and latency, so an effort or prompt change can be read off the logs
    # instead of guessed: a cache_read of zero across calls means the cached prefix broke,
    # and output_tokens is where effort shows up.
    usage = getattr(response, "usage", None)
    logger.info(
        "anthropic_call",
        route=route,
        latency_ms=int((time.monotonic() - started) * 1000),
        stop_reason=getattr(response, "stop_reason", None),
        input_tokens=getattr(usage, "input_tokens", None),
        cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", None),
        cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
    )


def _parsed[DecisionT: BaseModel](response: ParsedMessage[DecisionT], message: str) -> DecisionT:
    # A safety refusal or a response cut at `max_tokens` carries no complete JSON, and the
    # model has no server-side fallback to retry on. Raising lets every caller degrade the
    # way it already does for a provider outage: keyword classification, an AMBIGUOUS
    # confirmation, or a PROVIDER_ERROR grounding attempt that routes to a person.
    if response.stop_reason in {"refusal", "max_tokens"} or response.parsed_output is None:
        raise ValueError(f"{message} (stop_reason={response.stop_reason})")
    return response.parsed_output
