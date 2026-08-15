"""Compiles the kiosk orchestration graphs.

No checkpointer is passed to any `.compile()` call here -- see `state.py` for why.
Each graph is compiled once at import time and reused across requests; the only
per-request state is the `OrchestrationState` dict and `GraphContext` passed to
`ainvoke()`.

`finalize_subgraph` is compiled once and added as a node to both `confirmation_graph`
and `identification_graph` -- the same compiled instance, mirroring how the pre-graph
`_finalize` method was called from both `confirm()` and `identify()`.
"""

from langgraph.graph import END, START, StateGraph

from app.services.graph import (
    confirmation_nodes,
    finalize_nodes,
    identification_nodes,
    turn_nodes,
)
from app.services.graph.state import GraphContext, OrchestrationState


def build_turn_graph():
    builder = StateGraph(OrchestrationState, context_schema=GraphContext)
    builder.add_node("guard_turn", turn_nodes.guard_turn, destinations=("mask_pii", END))
    builder.add_node("mask_pii", turn_nodes.mask_pii)
    builder.add_node("classify", turn_nodes.classify)
    builder.add_node("clarify", turn_nodes.clarify)
    builder.add_node("force_human", turn_nodes.force_human)
    builder.add_node("accept", turn_nodes.accept)
    builder.add_node("decline", turn_nodes.decline)
    builder.add_node("persist_requirement", turn_nodes.persist_requirement)

    builder.add_edge(START, "guard_turn")
    builder.add_edge("mask_pii", "classify")
    builder.add_conditional_edges(
        "classify",
        turn_nodes.route_ambiguity,
        {
            "clarify": "clarify",
            "force_human": "force_human",
            "accept": "accept",
            "decline": "decline",
        },
    )
    builder.add_edge("clarify", "persist_requirement")
    builder.add_edge("force_human", "persist_requirement")
    builder.add_edge("accept", "persist_requirement")
    builder.add_edge("decline", "persist_requirement")
    builder.add_edge("persist_requirement", END)

    return builder.compile(name="turn_graph")


def build_finalize_subgraph():
    builder = StateGraph(OrchestrationState, context_schema=GraphContext)
    builder.add_node(
        "ticket_guard", finalize_nodes.ticket_guard, destinations=("assign_priority", END)
    )
    builder.add_node("assign_priority", finalize_nodes.assign_priority)
    builder.add_node("attempt_grounding", finalize_nodes.attempt_grounding)
    builder.add_node("automatic_ticket", finalize_nodes.automatic_ticket)
    builder.add_node("route_human", finalize_nodes.route_human)
    builder.add_node("persist_ticket", finalize_nodes.persist_ticket)

    builder.add_edge(START, "ticket_guard")
    builder.add_conditional_edges(
        "assign_priority",
        finalize_nodes.eligibility_gate,
        {"attempt_grounding": "attempt_grounding", "route_human": "route_human"},
    )
    builder.add_conditional_edges(
        "attempt_grounding",
        finalize_nodes.verify_grounding,
        {"automatic_ticket": "automatic_ticket", "route_human": "route_human"},
    )
    builder.add_edge("automatic_ticket", "persist_ticket")
    builder.add_edge("route_human", "persist_ticket")
    builder.add_edge("persist_ticket", END)

    return builder.compile(name="finalize_subgraph")


def build_confirmation_graph(finalize_subgraph):
    builder = StateGraph(OrchestrationState, context_schema=GraphContext)
    builder.add_node("load_and_guard", confirmation_nodes.load_and_guard)
    builder.add_node("heal_decision", confirmation_nodes.heal_decision)
    builder.add_node(
        "handle_replay",
        confirmation_nodes.handle_replay,
        destinations=(END, "finalize", "validate_fresh_confirmation"),
    )
    builder.add_node(
        "validate_fresh_confirmation",
        confirmation_nodes.validate_fresh_confirmation,
        destinations=(END, "apply_confirmation"),
    )
    builder.add_node(
        "apply_confirmation",
        confirmation_nodes.apply_confirmation,
        destinations=(END, "finalize"),
    )
    builder.add_node("finalize", finalize_subgraph)

    builder.add_edge(START, "load_and_guard")
    builder.add_edge("load_and_guard", "heal_decision")
    builder.add_conditional_edges(
        "heal_decision",
        confirmation_nodes.route_replay,
        {"replay": "handle_replay", "fresh": "validate_fresh_confirmation"},
    )
    builder.add_edge("finalize", END)

    return builder.compile(name="confirmation_graph")


def build_identification_graph(finalize_subgraph):
    builder = StateGraph(OrchestrationState, context_schema=GraphContext)
    builder.add_node(
        "guard_identification",
        identification_nodes.guard_identification,
        destinations=("resolve_client_reference", END),
    )
    builder.add_node("resolve_client_reference", identification_nodes.resolve_client_reference)
    builder.add_node("persist_identification", identification_nodes.persist_identification)
    builder.add_node("finalize", finalize_subgraph)

    builder.add_edge(START, "guard_identification")
    builder.add_edge("resolve_client_reference", "persist_identification")
    builder.add_edge("persist_identification", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile(name="identification_graph")


turn_graph = build_turn_graph()
finalize_subgraph = build_finalize_subgraph()
confirmation_graph = build_confirmation_graph(finalize_subgraph)
identification_graph = build_identification_graph(finalize_subgraph)
