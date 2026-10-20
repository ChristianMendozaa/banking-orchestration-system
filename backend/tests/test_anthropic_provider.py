from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domain.enums import Category, ConfirmationIntent, ConsultationLevel
from app.domain.schemas import (
    ClassificationDecision,
    ConfirmationReading,
    GroundedAnswerDecision,
)
from app.services.anthropic_provider import AnthropicProvider
from app.services.prompts import (
    CLASSIFICATION_SYSTEM_PROMPT,
    CONFIRMATION_READING_SYSTEM_PROMPT,
    GROUNDED_ANSWER_SYSTEM_PROMPT,
)
from tests.conftest import settings_for_tests

pytestmark = [pytest.mark.unit]


def _provider() -> AnthropicProvider:
    provider = object.__new__(AnthropicProvider)
    provider.settings = settings_for_tests.model_copy(
        update={"classification_reasoning_effort": "low", "grounding_reasoning_effort": "medium"}
    )
    provider.client = SimpleNamespace(messages=SimpleNamespace(parse=AsyncMock()))
    return provider


def _message(parsed: object, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(parsed_output=parsed, stop_reason=stop_reason)


def _decision() -> ClassificationDecision:
    return ClassificationDecision(
        category=Category.CONSULTA_GENERAL,
        consultation_level=ConsultationLevel.GENERAL,
        confidence=0.9,
        ambiguous=False,
        summary="Consulta de horarios",
        customer_summary="Necesitas conocer los horarios de atención.",
    )


def _chunk() -> SimpleNamespace:
    return SimpleNamespace(
        chunk=SimpleNamespace(id="chunk-1", page=3, content="Atención de lunes a viernes."),
        document=SimpleNamespace(title="Horarios"),
    )


async def test_classify_sends_a_cached_system_prompt_and_the_classification_effort() -> None:
    provider = _provider()
    decision = _decision()
    provider.client.messages.parse.return_value = _message(decision)

    assert await provider.classify("horarios") == decision

    call = provider.client.messages.parse.call_args.kwargs
    assert call["model"] == provider.settings.orchestration_model
    assert call["system"] == [
        {
            "type": "text",
            "text": CLASSIFICATION_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    assert call["messages"] == [{"role": "user", "content": "horarios"}]
    assert call["output_format"] is ClassificationDecision
    assert call["output_config"] == {"effort": "low"}
    # Room for adaptive thinking on top of the JSON, or the answer never arrives.
    assert call["max_tokens"] >= 4096
    # Claude Haiku 5.5 rejects non-default sampling parameters with a 400.
    assert not {"temperature", "top_p", "top_k", "thinking"} & call.keys()


async def test_read_confirmation_puts_summary_and_reply_in_the_user_turn() -> None:
    provider = _provider()
    reading = ConfirmationReading(intent=ConfirmationIntent.CONFIRM)
    provider.client.messages.parse.return_value = _message(reading)

    assert await provider.read_confirmation("Consultar horarios", "así es") == reading

    call = provider.client.messages.parse.call_args.kwargs
    assert call["system"][0]["text"] == CONFIRMATION_READING_SYSTEM_PROMPT
    assert call["messages"] == [
        {
            "role": "user",
            "content": (
                "Resumen que el kiosco leyo: Consultar horarios\nRespuesta de la persona: así es"
            ),
        }
    ]
    assert call["output_format"] is ConfirmationReading
    assert call["output_config"] == {"effort": "low"}


async def test_grounded_answer_sends_branch_and_numbered_evidence() -> None:
    provider = _provider()
    provider.client.messages.parse.return_value = _message(
        GroundedAnswerDecision(
            answer="Atención de lunes a viernes.",
            spoken="Atención de lunes a viernes.",
            supported=True,
            cited_evidence_refs=[1],
        )
    )

    grounded = await provider.grounded_answer("horarios", [_chunk()])

    assert grounded.supported is True
    call = provider.client.messages.parse.call_args.kwargs
    assert call["system"][0]["text"] == GROUNDED_ANSWER_SYSTEM_PROMPT
    content = call["messages"][0]["content"]
    assert f"Sucursal actual del kiosco: {settings_for_tests.branch_name}" in content
    assert "Consulta enmascarada: horarios" in content
    assert '<evidence ref="1" document="Horarios" page="3">' in content
    assert call["output_format"] is GroundedAnswerDecision
    assert call["output_config"] == {"effort": "medium"}


@pytest.mark.parametrize(
    ("stop_reason", "parsed"),
    [
        # A safety classifier declined; there is no server-side fallback on this model.
        ("refusal", None),
        # Thinking used up the budget before the JSON was finished.
        ("max_tokens", None),
        # Even a parse the SDK managed must not be trusted once the response was cut.
        ("max_tokens", "partial"),
        ("end_turn", None),
    ],
)
async def test_incomplete_responses_raise_so_callers_degrade(
    stop_reason: str, parsed: str | None
) -> None:
    provider = _provider()
    payloads = {
        "classify": _decision(),
        "read_confirmation": ConfirmationReading(intent=ConfirmationIntent.CONFIRM),
    }
    calls = [
        ("clasificacion estructurada", provider.classify, ("consulta",), "classify"),
        (
            "lectura de confirmacion",
            provider.read_confirmation,
            ("Consultar horarios", "eh"),
            "read_confirmation",
        ),
        ("respuesta fundamentada", provider.grounded_answer, ("consulta", []), None),
    ]
    for match, method, args, payload_key in calls:
        output = payloads.get(payload_key) if parsed == "partial" else None
        provider.client.messages.parse.return_value = _message(output, stop_reason)
        with pytest.raises(ValueError, match=match):
            await method(*args)
