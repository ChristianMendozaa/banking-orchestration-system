"""Stateful wrapper around one kiosk session.

Its three bound async methods are handed directly to `AssistantAgent(tools=[...])` --
AutoGen derives each tool's schema from the type hints and docstring, same pattern as
the MCP SDK.

It records two things the rest of the harness depends on:

1. **The full transcript** -- both sides of every exchange. The customer's own words only
   exist here (they are the tool arguments; the API never echoes them back), and both the
   dashboard's conversation view and the judge's dossier need them.
2. **What the system decided** -- category, consultation level, clarification and
   correction counts, reported PII types -- read from the system's own responses, never
   guessed.
"""

import time
from dataclasses import dataclass, field

from harness.client import KioskClient, KioskClientError, SessionHandle


@dataclass(slots=True)
class ExchangeRecord:
    """One customer action and the kiosk's response to it."""

    index: int
    tool: str
    customer_text: str | None
    kiosk_speech: str | None
    response: dict = field(default_factory=dict)
    latency_ms: int = 0
    error: str | None = None


class ConversationSession:
    def __init__(self, client: KioskClient, handle: SessionHandle) -> None:
        self._client = client
        self._handle = handle
        self.last_requirement_id: str | None = None
        self.last_category: str | None = None
        self.last_consultation_level: str | None = None
        self.clarification_rounds = 0
        self.correction_rounds = 0
        self.identification_attempts = 0
        self.finished = False
        self.exchanges: list[ExchangeRecord] = []
        self.requirement_ids: list[str] = []
        self.pii_types: list[str] = []
        self.errors: list[str] = []

    @classmethod
    async def start(
        cls, client: KioskClient, *, preferential_attention: bool = False
    ) -> "ConversationSession":
        handle = await client.create_session(preferential_attention=preferential_attention)
        return cls(client, handle)

    @property
    def session_id(self) -> str:
        return self._handle.session_id

    @property
    def handle(self) -> SessionHandle:
        return self._handle

    @property
    def client(self) -> KioskClient:
        """Exposed for the `protocol` scenario scripts, which drive the API directly
        instead of through an LLM customer."""
        return self._client

    def record_raw(
        self, label: str, request_summary: str, status_code: int, body: dict | None
    ) -> None:
        """Append a raw request/response pair to the transcript.

        Protocol scenarios have no customer utterances, but the dashboard and the judge
        still need to see what was sent and what came back.
        """
        code = (body or {}).get("code")
        message = (body or {}).get("message") or (body or {}).get("next_action")
        self.exchanges.append(
            ExchangeRecord(
                index=len(self.exchanges),
                tool=label,
                customer_text=request_summary,
                kiosk_speech=f"HTTP {status_code}" + (f" {code}: {message}" if code else ""),
                response=body or {},
            )
        )

    @property
    def customer_utterances(self) -> list[str]:
        return [x.customer_text for x in self.exchanges if x.customer_text]

    @property
    def kiosk_utterances(self) -> list[str]:
        return [x.kiosk_speech for x in self.exchanges if x.kiosk_speech]

    async def send_turn(self, transcript: str, is_clarification: bool) -> str:
        """Envía lo que dice el cliente al kiosco (una descripción de su situación, o la
        respuesta a una pregunta de aclaración). Usa is_clarification=true unicamente si
        el kiosco pidio aclarar en el turno anterior."""
        response = await self._call(
            "send_turn",
            transcript,
            lambda: self._client.send_turn(
                self._handle, transcript, is_clarification=is_clarification
            ),
        )
        if response is None:
            return self._last_error_description()
        self.last_requirement_id = response.get("requirement_id")
        if self.last_requirement_id and self.last_requirement_id not in self.requirement_ids:
            self.requirement_ids.append(self.last_requirement_id)
        self.last_category = response.get("category")
        self.last_consultation_level = response.get("consultation_level")
        for pii_type in response.get("pii_types") or []:
            if pii_type not in self.pii_types:
                self.pii_types.append(pii_type)
        if response.get("next_action") == "CLARIFY":
            self.clarification_rounds += 1
        if response.get("next_action") == "DECLINE":
            self.finished = True
        return self._describe(response)

    async def send_confirmation(self, confirmed: bool) -> str:
        """Confirma (true) o rechaza/corrige (false) el resumen que propuso el kiosco."""
        if not self.last_requirement_id:
            return "Error: aun no hay un resumen que confirmar; llama primero a send_turn."
        spoken = "Sí, así es, confirmo." if confirmed else "No, eso no es lo que necesito."
        response = await self._call(
            "send_confirmation",
            spoken,
            lambda: self._client.send_confirmation(
                self._handle, self.last_requirement_id, confirmed
            ),
        )
        if response is None:
            return self._last_error_description()
        if not confirmed:
            self.correction_rounds += 1
        self._check_finished(response)
        return self._describe(response)

    async def send_identification(self, identifier: str) -> str:
        """Proporciona el numero de CI del cliente cuando el kiosco lo solicita."""
        self.identification_attempts += 1
        response = await self._call(
            "send_identification",
            f"Mi CI es {identifier}.",
            lambda: self._client.send_identification(self._handle, identifier),
        )
        if response is None:
            return self._last_error_description()
        self._check_finished(response)
        return self._describe(response)

    async def final_status(self) -> dict:
        return await self._client.get_status(self._handle)

    async def _call(self, tool: str, customer_text: str, operation) -> dict | None:
        """Run one API call, timing it and recording both sides of the exchange.

        A `KioskClientError` is recorded and reported back to the agent as a tool result
        rather than propagated: a mid-flow 409 is something the scenario should be scored
        on, and aborting the agent loop would discard the transcript that explains it.
        """
        started = time.monotonic()
        try:
            response = await operation()
        except KioskClientError as exc:
            self.errors.append(f"{tool}: {exc}")
            self.exchanges.append(
                ExchangeRecord(
                    index=len(self.exchanges),
                    tool=tool,
                    customer_text=customer_text,
                    kiosk_speech=None,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    error=str(exc),
                )
            )
            return None
        self.exchanges.append(
            ExchangeRecord(
                index=len(self.exchanges),
                tool=tool,
                customer_text=customer_text,
                kiosk_speech=self._spoken_text(response),
                response=response,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        )
        return response

    def _last_error_description(self) -> str:
        error = self.errors[-1] if self.errors else "error desconocido"
        return (
            f"El kiosco devolvio un error: {error}. "
            "No reintentes la misma accion; responde exactamente TERMINATE."
        )

    @staticmethod
    def _spoken_text(response: dict) -> str | None:
        return (
            response.get("clarification_question")
            or response.get("speech_text")
            or response.get("response")
        )

    def _check_finished(self, response: dict) -> None:
        if response.get("next_action") == "COMPLETE":
            self.finished = True

    def _describe(self, response: dict) -> str:
        parts = [f"next_action={response.get('next_action')}"]
        question = response.get("clarification_question")
        if question:
            parts.append(f"pregunta_aclaracion={question!r}")
        speech = response.get("speech_text")
        if speech:
            parts.append(f"kiosco_dice={speech!r}")
        if self.finished:
            parts.append(
                "La sesion ha terminado. No llames mas herramientas; "
                "responde exactamente TERMINATE."
            )
        return " | ".join(parts)
