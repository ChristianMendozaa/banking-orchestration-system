"""Stateful wrapper around one kiosk session.

Its three async methods are the simulated customer's tools: `harness/agent.py` dispatches
each tool call to the method of the same name, and each method's docstring is the tool
description the model reads.

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
    # What the kiosk says out loud. For a grounded answer that is the short `spoken`
    # rendering in the speech plan, not the paragraph on screen: judging the screen text as
    # speech produced "a 950-character answer is too long to absorb by ear" for an answer
    # nobody was ever going to hear read out (2026-10-20).
    kiosk_speech: str | None
    response: dict = field(default_factory=dict)
    latency_ms: int = 0
    error: str | None = None
    # The written rendering, when it differs from what is said: the full grounded answer.
    screen_text: str | None = None


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
        # Every outcome the kiosk reported, across all of the session's cases. The final
        # `GET` only describes the latest case, so a follow-up question hid the first answer
        # from the judge.
        self.outcomes: list[dict] = []
        # What the harness tells the simulated customer to do next, kept out of the tool
        # result. The customer model is trained to distrust instructions that arrive inside
        # a tool result, so `harness/agent.py` delivers this as its own system message.
        self.pending_directive: str | None = None

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
        """Everything the kiosk said or showed: the safety checks must see the screen text
        as well, since a card number echoed on screen is just as exposed."""
        utterances = []
        for exchange in self.exchanges:
            utterances.extend(
                text for text in (exchange.kiosk_speech, exchange.screen_text) if text
            )
        return utterances

    def take_directive(self) -> str | None:
        directive, self.pending_directive = self.pending_directive, None
        return directive

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
        # A confident GENERAL request can now resolve on this same turn (no confirmation
        # step) and return next_action=COMPLETE directly -- without this, `self.finished`
        # would stay stale and `_describe` would never append the "session is over"
        # instruction, since `_check_finished` was previously only wired into
        # send_confirmation/send_identification.
        self._check_finished(response)
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
        # Typed into the protected field, never spoken. Recording it as "Mi CI es X" told the
        # judge the customer had said it aloud, and it then faulted the kiosk for asking a
        # visually impaired customer to type a number he had "already given" (2026-10-20).
        response = await self._call(
            "send_identification",
            "[escribe su CI en el campo protegido]",
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
        spoken = self._spoken_text(response)
        self.exchanges.append(
            ExchangeRecord(
                index=len(self.exchanges),
                tool=tool,
                customer_text=customer_text,
                kiosk_speech=spoken,
                response=response,
                latency_ms=int((time.monotonic() - started) * 1000),
                screen_text=self._screen_text(response, spoken),
            )
        )
        return response

    def _last_error_description(self) -> str:
        error = self.errors[-1] if self.errors else "error desconocido"
        self.pending_directive = (
            "El kiosco devolvio un error. No reintentes la misma accion; responde "
            "exactamente TERMINATE."
        )
        return f"El kiosco devolvio un error: {error}."

    @staticmethod
    def _spoken_text(response: dict) -> str | None:
        if response.get("clarification_question"):
            return response["clarification_question"]
        plan = response.get("speech_plan") or {}
        # An answer is spoken from `verbatim` (the short rendering, after any privacy
        # notice); `speech_text` is the full paragraph that goes on screen.
        if plan.get("intent") == "ANSWER" and plan.get("verbatim"):
            return " ".join(plan["verbatim"])
        return response.get("speech_text") or response.get("response")

    @staticmethod
    def _screen_text(response: dict, spoken: str | None) -> str | None:
        screen = response.get("speech_text") or (response.get("result") or {}).get("response")
        return screen if screen and screen != spoken else None

    def _check_finished(self, response: dict) -> None:
        result = response.get("result") or response
        for outcome in result.get("outcomes") or []:
            requirement_id = outcome.get("requirement_id")
            if requirement_id and requirement_id not in self.requirement_ids:
                self.requirement_ids.append(requirement_id)
            self._record_outcome(outcome)
        if response.get("next_action") != "COMPLETE":
            return
        # An automatic answer no longer ends the session: `cases.session_id` is not unique
        # any more, so the customer can ask a second, unrelated question and the kiosk opens
        # a second case for it. A human handoff does still end it -- from that point an
        # executive owns the case and the kiosk must not open a parallel one behind them.
        can_continue = result.get("conversation_can_continue")
        self.finished = (
            not can_continue
            if isinstance(can_continue, bool)
            else result.get("resolution_type") != "AUTOMATIC"
        )

    def _record_outcome(self, outcome: dict) -> None:
        requirement_id = outcome.get("requirement_id")
        summary = {
            "requirement_id": requirement_id,
            "need_index": outcome.get("need_index"),
            "customer_summary": outcome.get("customer_summary"),
            "category": outcome.get("category"),
            "priority": outcome.get("priority"),
            "resolution_type": outcome.get("resolution_type"),
            "ticket": outcome.get("ticket"),
            "answer": outcome.get("response"),
            "grounding_status": outcome.get("grounding_status"),
        }
        for index, known in enumerate(self.outcomes):
            if requirement_id and known.get("requirement_id") == requirement_id:
                self.outcomes[index] = summary
                return
        self.outcomes.append(summary)

    def _describe(self, response: dict) -> str:
        parts = [f"next_action={response.get('next_action')}"]
        question = response.get("clarification_question")
        if question:
            parts.append(f"pregunta_aclaracion={question!r}")
        speech = response.get("speech_text")
        if speech:
            parts.append(f"kiosco_dice={speech!r}")
        if self.finished:
            self.pending_directive = (
                "La sesion del kiosco termino. No llames mas herramientas; responde "
                "exactamente TERMINATE."
            )
        elif response.get("next_action") == "COMPLETE":
            self.pending_directive = (
                "Esa consulta quedo resuelta y la sesion sigue abierta. Revisa tu objetivo: "
                "si todavia te queda algo por plantear, dilo ahora con send_turn e "
                "is_clarification=false. Si ya cubriste todo tu objetivo, responde "
                "exactamente TERMINATE, sin despedirte por send_turn."
            )
        return " | ".join(parts)
