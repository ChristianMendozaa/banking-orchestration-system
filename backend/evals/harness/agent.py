"""Builds the Simulated Customer agent.

The genuinely multi-turn part of a kiosk session -- reacting to a clarification question,
a confirmation request, or an identification request, where each next message depends on
the *real* API's previous response -- is a plain tool-calling loop over the Messages API,
with three tools bound to a live `ConversationSession`. The loop is written out here rather
than borrowed from an agent framework: it is short, and the kiosk is a state machine whose
calls must run one at a time in the order the model made them.

The system message is assembled from three separate pieces so the same situation can be
re-tested through a different mouth: the scenario's `goal` (what this person needs), the
`PersonaStyle` (how they talk), and the identity-card number they will hand over if asked.
Keeping style out of the goal is what makes `tarjeta_robada_angustiado` and
`tarjeta_extraviada_calmado` a controlled comparison rather than two unrelated tests.
"""

import inspect
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, ToolParam, ToolResultBlockParam

from harness.scenarios.models import Scenario
from harness.session import ConversationSession

logger = structlog.get_logger()

# Each customer turn is one short Spanish sentence or one tool call.
CUSTOMER_MAX_TOKENS = 4096
# Model requests per scenario. A full fraud flow -- turn, clarification, confirmation,
# identification, a second requirement -- needs about half of this; the cap only stops a
# customer that keeps calling tools after the kiosk has nothing left to say.
MAX_TOOL_ITERATIONS = 12
# Adaptive thinking at the lowest effort, rather than thinking turned off. The customer is
# role-play plus picking one of three tools, so it needs little reasoning -- but effort is
# the control Claude Haiku 5.5 is built around, and with thinking disabled the 2026-10-20
# run's customer answered "the session is still open, re-read your goal" with a goodbye
# through `send_turn` instead of TERMINATE. Effort also keeps working if `--customer-model`
# points at a model that rejects `{"type": "disabled"}`.
CUSTOMER_EFFORT = "low"


def _tool(name: str, properties: dict[str, dict]) -> ToolParam:
    """The description is the session method's own docstring, so what the model reads and
    what the method does are documented in one place."""
    return {
        "name": name,
        "description": inspect.getdoc(getattr(ConversationSession, name)) or "",
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
        "strict": True,
    }


CUSTOMER_TOOLS: list[ToolParam] = [
    _tool(
        "send_turn",
        {"transcript": {"type": "string"}, "is_clarification": {"type": "boolean"}},
    ),
    _tool("send_confirmation", {"confirmed": {"type": "boolean"}}),
    _tool("send_identification", {"identifier": {"type": "string"}}),
]

SYSTEM_MESSAGE_TEMPLATE = """\
Actuas como un cliente de un banco boliviano en un kiosco de atencion. Tu situacion:

{goal}

Como hablas: {style}

Habla en primera persona, en espanol boliviano natural y breve, como lo haria una \
persona real -- no como un sistema, y nunca describas lo que estas haciendo. Usa las \
herramientas disponibles para interactuar con el kiosco, nunca inventes su respuesta:
- send_turn: para contar tu situacion, o para responder cuando el kiosco pide aclarar \
(is_clarification=true solo en ese caso).
- send_confirmation: para confirmar o corregir el resumen que el kiosco te propone.
- send_identification: para dar tu CI cuando el kiosco lo solicita explicitamente.
{identity}
Cada herramienta te dice el next_action del kiosco. Sigue ese next_action hasta el final, \
aunque creas que ya dijiste todo:
- CLARIFY: responde con send_turn e is_clarification=true.
- CONFIRM: responde con send_confirmation (true si el resumen es correcto, false si no).
- CAPTURE: el kiosco pide que vuelvas a describir tu situacion; responde con send_turn \
e is_clarification=false (no es una aclaracion, es un requerimiento nuevo).
- IDENTIFY: responde con send_identification.
- COMPLETE: el kiosco resolvio o encamino lo que pediste. Si la sesion termino, responde \
exactamente TERMINATE. Si sigue abierta, relee tu objetivo: si incluye algo que todavia no \
planteaste, plantealo ahora con send_turn e is_clarification=false; si ya lo cubriste todo, \
responde exactamente TERMINATE. Despedirte o agradecer no es parte de tu objetivo: no lo \
hagas con send_turn.
- DECLINE: el kiosco no puede ayudarte con esto y la sesion termino; responde exactamente \
TERMINATE. No insistas ni vuelvas a llamar send_turn.

No llames a send_confirmation ni a send_identification si el kiosco no lo pidio. No dejes \
la conversacion a medias: solo respondes TERMINATE cuando una herramienta indique COMPLETE \
o informe un error. Despues de cada herramienta puede llegarte un mensaje de sistema del \
entorno de prueba con la siguiente indicacion; siguela.
"""

_WITH_CI = """\
- Tu numero de CI es {identifier}. Entregalo tal cual, solo si el kiosco te lo pide.
"""
# Deliberately does NOT tell the agent to explain itself with send_turn: the state machine
# rejects a turn while the session is AWAITING_IDENTIFICATION (409 INVALID_SESSION_STATE),
# so that instruction would manufacture an API error the kiosk is not responsible for.
_WITHOUT_CI = """\
- No tienes ningun documento contigo. Si el kiosco te pide el CI no puedes darselo y no \
debes inventar un numero: responde exactamente TERMINATE y no llames mas herramientas.
"""


def build_system_message(scenario: Scenario) -> str:
    identity = (
        _WITH_CI.format(identifier=scenario.identifier) if scenario.identifier else _WITHOUT_CI
    )
    return SYSTEM_MESSAGE_TEMPLATE.format(
        goal=scenario.goal,
        style=scenario.style.instruction,
        identity=identity,
    )


class SimulatedCustomer:
    def __init__(
        self,
        *,
        client: AsyncAnthropic,
        model: str,
        session: ConversationSession,
        scenario: Scenario,
    ) -> None:
        self._client = client
        self._model = model
        self._scenario = scenario
        self._session = session
        self._system = build_system_message(scenario)
        self._handlers = {tool["name"]: getattr(session, tool["name"]) for tool in CUSTOMER_TOOLS}

    async def run(self, task: str) -> None:
        """Talk to the kiosk until the model stops calling tools -- its `TERMINATE` reply --
        or `MAX_TOOL_ITERATIONS` requests have been made. Everything worth keeping is
        recorded on the session, so nothing is returned."""
        messages: list[MessageParam] = [{"role": "user", "content": task}]
        for _ in range(MAX_TOOL_ITERATIONS):
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=CUSTOMER_MAX_TOKENS,
                system=self._system,
                tools=CUSTOMER_TOOLS,
                # One call per response: two `send_turn`s racing on one kiosk session
                # would test the harness's concurrency, not the kiosk.
                tool_choice={"type": "auto", "disable_parallel_tool_use": True},
                output_config={"effort": CUSTOMER_EFFORT},
                messages=messages,
            )
            # The whole content goes back, not just the text, so tool_use blocks (and any
            # thinking blocks, were thinking ever turned on) reach the next request intact.
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason != "tool_use":
                if response.stop_reason in {"max_tokens", "refusal"}:
                    logger.warning(
                        "customer_stopped_early",
                        scenario=self._scenario.name,
                        stop_reason=response.stop_reason,
                    )
                return
            results = [
                await self._call_tool(block.id, block.name, block.input)
                for block in response.content
                if block.type == "tool_use"
            ]
            messages.append({"role": "user", "content": results})
            # The tool result carries only what the kiosk did. What the harness wants next
            # goes in its own mid-conversation system message: the model reads instructions
            # inside a tool result as possibly injected text and may not follow them.
            directive = self._session.take_directive()
            if directive:
                messages.append({"role": "system", "content": directive})

    async def _call_tool(
        self, tool_use_id: str, name: str, arguments: dict[str, Any]
    ) -> ToolResultBlockParam:
        """A failure goes back to the model as an error result rather than ending the run:
        the transcript up to that point is still the evidence the scenario is scored on.
        Kiosk API errors never get here -- `ConversationSession._call` already turns them
        into a tool result telling the customer to stop."""
        handler = self._handlers.get(name)
        try:
            if handler is None:
                raise LookupError(f"unknown tool {name!r}")
            content = await handler(**arguments)
        except Exception as exc:  # noqa: BLE001 - reported to the model, not raised
            logger.warning(
                "customer_tool_failed", scenario=self._scenario.name, tool=name, error=str(exc)
            )
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": f"Error: {type(exc).__name__}: {exc}",
                "is_error": True,
            }
        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}


def build_customer_agent(
    *,
    client: AsyncAnthropic,
    model: str,
    session: ConversationSession,
    scenario: Scenario,
) -> SimulatedCustomer:
    """Takes a client rather than building one so the caller owns its lifecycle: the
    client holds an HTTP connection pool, and one per scenario has to be closed."""
    return SimulatedCustomer(client=client, model=model, session=session, scenario=scenario)
