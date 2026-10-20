from typing import Any

import httpx
from openai import AsyncOpenAI

from app.core.config import Settings
from app.core.errors import AppError
from app.services.prompts import KIOSK_VOICE_INSTRUCTIONS

# Re-exported so `app.services.openai_provider.KIOSK_VOICE_INSTRUCTIONS` keeps working for
# callers and tests that have always imported it from here. The text itself lives in
# `app.services.prompts.voice`.
__all__ = ["KIOSK_VOICE_INSTRUCTIONS", "OpenAIProvider"]


class OpenAIProvider:
    """Embeddings and the kiosk's realtime voice channel.

    The orchestration decisions themselves -- classification, confirmation reading and
    grounded answers -- are made by `AnthropicProvider`.
    """

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
            # The application owns the turn, not the model. With `create_response` on, the
            # model answered whatever the microphone heard the moment it went quiet -- on
            # 2026-10-14 that was a room full of people, before the kiosk had even
            # greeted anyone -- and it did so before the transcription the business logic
            # runs on had landed. The browser now waits for that transcription, asks the
            # backend, and requests the response itself.
            #
            # It still stops when the customer starts (`interrupt_response`), and it waits
            # longer before deciding they are done (`eagerness: low`): "Quiero..." followed
            # by a breath used to be sent to the bank as a whole request.
            "turn_detection": {
                "type": "semantic_vad",
                "eagerness": "low",
                "create_response": False,
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
