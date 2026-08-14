"""Stateful wrapper around one kiosk session.

Its three bound async methods are handed directly to `AssistantAgent(tools=[...])` --
AutoGen derives each tool's schema from the type hints and docstring, same pattern as
the MCP SDK. It also tracks what the Evaluator needs: which category/consultation_level
the system settled on, and how many clarification rounds actually happened -- read from
the system's own responses, not guessed.
"""

from harness.client import KioskClient, SessionHandle


class ConversationSession:
    def __init__(self, client: KioskClient, handle: SessionHandle) -> None:
        self._client = client
        self._handle = handle
        self.last_requirement_id: str | None = None
        self.last_category: str | None = None
        self.last_consultation_level: str | None = None
        self.clarification_rounds = 0
        self.finished = False
        self.log: list[dict] = []

    @classmethod
    async def start(
        cls, client: KioskClient, *, preferential_attention: bool = False
    ) -> "ConversationSession":
        handle = await client.create_session(preferential_attention=preferential_attention)
        return cls(client, handle)

    @property
    def session_id(self) -> str:
        return self._handle.session_id

    async def send_turn(self, transcript: str, is_clarification: bool) -> str:
        """Envía lo que dice el cliente al kiosco (una descripción de su situación, o la
        respuesta a una pregunta de aclaración). Usa is_clarification=true unicamente si
        el kiosco pidio aclarar en el turno anterior."""
        response = await self._client.send_turn(
            self._handle, transcript, is_clarification=is_clarification
        )
        self._record("send_turn", response)
        self.last_requirement_id = response.get("requirement_id")
        self.last_category = response.get("category")
        self.last_consultation_level = response.get("consultation_level")
        if response.get("next_action") == "CLARIFY":
            self.clarification_rounds += 1
        return self._describe(response)

    async def send_confirmation(self, confirmed: bool) -> str:
        """Confirma (true) o rechaza/corrige (false) el resumen que propuso el kiosco."""
        if not self.last_requirement_id:
            return "Error: aun no hay un resumen que confirmar; llama primero a send_turn."
        response = await self._client.send_confirmation(
            self._handle, self.last_requirement_id, confirmed
        )
        self._record("send_confirmation", response)
        self._check_finished(response)
        return self._describe(response)

    async def send_identification(self, identifier: str) -> str:
        """Proporciona el numero de CI del cliente cuando el kiosco lo solicita."""
        response = await self._client.send_identification(self._handle, identifier)
        self._record("send_identification", response)
        self._check_finished(response)
        return self._describe(response)

    async def final_status(self) -> dict:
        return await self._client.get_status(self._handle)

    def _record(self, tool: str, response: dict) -> None:
        self.log.append({"tool": tool, "response": response})

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
