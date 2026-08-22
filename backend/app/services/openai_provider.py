from typing import TYPE_CHECKING, Any

import httpx
from openai import AsyncOpenAI

from app.core.config import Settings
from app.core.errors import AppError
from app.domain.schemas import ClassificationDecision, GroundedAnswerDecision
from app.services.prompts import (
    CLASSIFICATION_SYSTEM_PROMPT,
    GROUNDED_ANSWER_SYSTEM_PROMPT,
    KIOSK_VOICE_INSTRUCTIONS,
)

if TYPE_CHECKING:
    from app.knowledge.repository import RetrievedChunk


# Re-exported so `app.services.openai_provider.KIOSK_VOICE_INSTRUCTIONS` keeps working for
# callers and tests that have always imported it from here. The text itself lives in
# `app.services.prompts.voice`.
__all__ = ["KIOSK_VOICE_INSTRUCTIONS", "OpenAIProvider"]


class OpenAIProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        api_key = settings.openai_api_key.get_secret_value()
        self.client = AsyncOpenAI(api_key=api_key, timeout=settings.openai_timeout_seconds)

    async def create_realtime_client_secret(self, safety_identifier: str) -> dict[str, Any]:
        # Built once and both sent and echoed back, so the browser cannot end up applying a
        # different audio configuration than the one this secret was minted with. The Agents
        # SDK substitutes its own defaults for every field of `audio.input` the caller leaves
        # out -- `gpt-4o-mini-transcribe` instead of our transcription model, plain
        # `semantic_vad` without the interruption settings, no noise reduction -- and its
        # session.update lands after ours, so whatever the browser holds is what governs.
        audio_input = {
            "noise_reduction": {"type": "near_field"},
            "transcription": {
                "model": self.settings.transcription_model,
                "language": "es",
            },
            # The model runs the conversation, so its own turn-taking is the
            # point: it answers when the customer stops, and it stops when the
            # customer starts.
            "turn_detection": {
                "type": "semantic_vad",
                "eagerness": "auto",
                "create_response": True,
                "interrupt_response": True,
            },
        }
        payload = {
            "session": {
                "type": "realtime",
                "model": self.settings.voice_model,
                "instructions": KIOSK_VOICE_INSTRUCTIONS,
                "output_modalities": ["audio"],
                # A kiosk answer that runs long is a kiosk answer nobody listens to, and an
                # unbounded one blocks the queue. Generous enough for a full grounded answer
                # read verbatim, short enough that a rambling turn gets cut.
                "max_output_tokens": 1200,
                "audio": {
                    "input": audio_input,
                    "output": {"voice": self.settings.realtime_voice},
                },
            }
        }
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "OpenAI-Safety-Identifier": safety_identifier,
        }
        try:
            async with httpx.AsyncClient(timeout=self.settings.openai_timeout_seconds) as client:
                response = await client.post(
                    "https://api.openai.com/v1/realtime/client_secrets",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError(
                "REALTIME_UNAVAILABLE",
                "No fue posible iniciar el canal de voz; inténtalo nuevamente",
                503,
            ) from exc
        # The browser builds its RealtimeAgent from these, so they have to come back with
        # the secret. The Agents SDK sends the agent's own instructions as the session
        # instructions on connect, which means whatever the browser holds is what actually
        # governs the conversation -- echoing them here keeps that copy from being a second,
        # drifting source of the persona.
        #
        # `audio_input` rides along for the same reason and is the same object that was just
        # minted, not a re-derivation of it: the browser has to re-send the whole audio input
        # block or lose it to SDK defaults, and a hand-written copy over there would make
        # `transcription_model` a setting only half the system obeys.
        session = data.get("session")
        if isinstance(session, dict):
            session.setdefault("instructions", KIOSK_VOICE_INSTRUCTIONS)
            session.setdefault("model", self.settings.voice_model)
            session.setdefault("voice", self.settings.realtime_voice)
            session.setdefault("audio_input", audio_input)
        return data

    async def classify(self, masked_text: str) -> ClassificationDecision:
        system = CLASSIFICATION_SYSTEM_PROMPT
        response = await self.client.responses.parse(
            model=self.settings.orchestration_model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": masked_text},
            ],
            # This call sits directly between the customer finishing a sentence and the kiosk
            # answering, so its latency is dead air the person hears -- on every turn, not just
            # the ones that reach the corpus. Measured on gpt-5.4-mini against this prompt:
            # 2.43s at the default effort, 1.57s at "low". The floor is "none", not "minimal":
            # the model rejects "minimal" with a 400 that lists none/low/medium/high/xhigh as
            # the valid set. See `classification_reasoning_effort` in core/config.py for why
            # the default sits at the floor and what to re-run before changing it.
            reasoning={"effort": self.settings.classification_reasoning_effort},
            text_format=ClassificationDecision,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("OpenAI no devolvio una clasificacion estructurada")
        return parsed

    async def embedding(self, text: str) -> list[float]:
        return (await self.embeddings([text]))[0]

    async def embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result: list[list[float]] = []
        for start in range(0, len(texts), 64):
            response = await self.client.embeddings.create(
                model=self.settings.embedding_model,
                input=texts[start : start + 64],
                dimensions=self.settings.embedding_dimensions,
            )
            result.extend(
                item.embedding for item in sorted(response.data, key=lambda item: item.index)
            )
        return result

    async def grounded_answer(
        self, summary: str, chunks: list["RetrievedChunk"]
    ) -> GroundedAnswerDecision:
        evidence = "\n\n".join(
            f'<evidence id="{item.chunk.id}" document="{item.document.title}" '
            f'page="{item.chunk.page}">\n{item.chunk.content}\n</evidence>'
            for item in chunks
        )
        response = await self.client.responses.parse(
            model=self.settings.orchestration_model,
            input=[
                {
                    "role": "system",
                    "content": GROUNDED_ANSWER_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": f"Consulta enmascarada: {summary}\n\nEvidencia:\n{evidence}",
                },
            ],
            # Same blocking turn as `classify`, immediately after it -- but held one step
            # higher on purpose. This is the call that decides whether the evidence really
            # answers the question, and a wrong "supported" reads invented banking information
            # to a customer. See `grounding_reasoning_effort` in core/config.py.
            reasoning={"effort": self.settings.grounding_reasoning_effort},
            text_format=GroundedAnswerDecision,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("OpenAI no devolvio una respuesta fundamentada estructurada")
        return parsed
