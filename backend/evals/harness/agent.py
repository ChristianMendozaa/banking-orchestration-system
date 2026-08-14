"""Builds the Simulated Customer agent.

Deliberately a single AutoGen agent, not two. The genuinely multi-turn part -- reacting
to clarification questions, confirmations, and identification requests, where each next
message depends on the *real* kiosk API's previous response -- is exactly AutoGen's
tool-calling loop (`max_tool_iterations`) applied to one agent with three tools bound to
a live `ConversationSession`.

There is deliberately no second "Evaluator" AutoGen agent: every check in evaluator.py is
objectively decidable from the system's own recorded state, so scoring is plain Python,
not a judgment call that would need an LLM -- the same principle the real orchestrator
uses for its own deterministic agents (PrioritizationAgent, DerivationAgent).
"""

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient

from harness.personas import Persona
from harness.session import ConversationSession

SYSTEM_MESSAGE_TEMPLATE = """\
Actuas como un cliente de un banco boliviano en un kiosco de atencion. Tu situacion:

{goal}

Habla en primera persona, en espanol boliviano natural y breve, como lo haria una \
persona real -- no como un sistema. Usa las herramientas disponibles para interactuar \
con el kiosco, nunca inventes su respuesta:
- send_turn: para contar tu situacion, o para responder cuando el kiosco pide aclarar \
(is_clarification=true solo en ese caso).
- send_confirmation: para confirmar o corregir el resumen que el kiosco te propone.
- send_identification: para dar tu CI cuando el kiosco lo solicita explicitamente.

No llames a send_confirmation ni a send_identification si el kiosco no lo pidio en su \
ultima respuesta. Cuando una herramienta te indique que la sesion termino, responde \
exactamente TERMINATE y no llames a ninguna otra herramienta.
"""


def build_customer_agent(
    *, model: str, session: ConversationSession, persona: Persona
) -> AssistantAgent:
    model_client = OpenAIChatCompletionClient(model=model)
    return AssistantAgent(
        name="cliente_simulado",
        model_client=model_client,
        tools=[session.send_turn, session.send_confirmation, session.send_identification],
        system_message=SYSTEM_MESSAGE_TEMPLATE.format(goal=persona.goal),
        max_tool_iterations=12,
    )
