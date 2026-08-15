"""Builds the Simulated Customer agent.

The genuinely multi-turn part of a kiosk session -- reacting to a clarification question,
a confirmation request, or an identification request, where each next message depends on
the *real* API's previous response -- is exactly AutoGen's tool-calling loop applied to one
agent with three tools bound to a live `ConversationSession`.

The system message is assembled from three separate pieces so the same situation can be
re-tested through a different mouth: the scenario's `goal` (what this person needs), the
`PersonaStyle` (how they talk), and the identity-card number they will hand over if asked.
Keeping style out of the goal is what makes `tarjeta_robada_angustiado` and
`tarjeta_extraviada_calmado` a controlled comparison rather than two unrelated tests.
"""

from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ChatCompletionClient

from harness.scenarios.models import Scenario
from harness.session import ConversationSession

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
- IDENTIFY: responde con send_identification.
- COMPLETE: la sesion termino; responde exactamente TERMINATE.
- DECLINE: el kiosco no puede ayudarte con esto y la sesion termino; responde exactamente \
TERMINATE. No insistas ni vuelvas a llamar send_turn.

No llames a send_confirmation ni a send_identification si el kiosco no lo pidio. No dejes \
la conversacion a medias: solo respondes TERMINATE cuando una herramienta indique COMPLETE \
o informe un error.
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
        _WITH_CI.format(identifier=scenario.identifier)
        if scenario.identifier
        else _WITHOUT_CI
    )
    return SYSTEM_MESSAGE_TEMPLATE.format(
        goal=scenario.goal,
        style=scenario.style.instruction,
        identity=identity,
    )


def build_customer_agent(
    *, model_client: ChatCompletionClient, session: ConversationSession, scenario: Scenario
) -> AssistantAgent:
    """Takes a client rather than a model name so the caller owns its lifecycle: the
    client holds an HTTP connection pool, and one per scenario has to be closed."""
    return AssistantAgent(
        name="cliente_simulado",
        model_client=model_client,
        tools=[session.send_turn, session.send_confirmation, session.send_identification],
        system_message=build_system_message(scenario),
        max_tool_iterations=12,
    )
