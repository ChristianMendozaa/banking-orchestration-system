"""Regenerates the orchestration-graph mermaid diagrams embedded in README.md.

Run after any change to app/services/graph/*.py:

    uv run python scripts/render_graph_diagrams.py

Diagrams are generated directly from the compiled LangGraph graphs
(`graph.get_graph().draw_mermaid()`), so this replaces the marked block in README.md
rather than requiring anyone to hand-edit the flowchart. See app/services/graph/builder.py
for the graphs themselves.
"""

from pathlib import Path

from app.services.graph.builder import (
    confirmation_graph,
    finalize_subgraph,
    identification_graph,
    turn_graph,
)

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"

START_MARKER = "<!-- BEGIN GENERATED GRAPH DIAGRAMS -->"
END_MARKER = "<!-- END GENERATED GRAPH DIAGRAMS -->"

GRAPHS = [
    (
        "turn_graph",
        turn_graph,
        "Handles `POST /kiosk/sessions/{id}/turns`. `finalize` is the shared subgraph "
        "below: a confident GENERAL classification reaches it through `auto_capture` "
        "without a confirmation round-trip (see `turn_nodes.requires_confirmation`).",
    ),
    (
        "confirmation_graph",
        confirmation_graph,
        "Handles `POST /kiosk/sessions/{id}/confirmation`. `finalize` is the same "
        "compiled subgraph `turn_graph` and `identification_graph` use.",
    ),
    (
        "identification_graph",
        identification_graph,
        "Handles `POST /kiosk/sessions/{id}/identification`.",
    ),
    (
        "finalize_subgraph",
        finalize_subgraph,
        "Compiled once in `builder.py` and added as the `finalize` node to all three "
        "graphs above -- the same compiled instance, not a copy.",
    ),
]


def render_block() -> str:
    parts = [START_MARKER]
    for name, graph, description in GRAPHS:
        parts.append(f"\n#### `{name}`\n\n{description}\n")
        parts.append("```mermaid")
        parts.append(graph.get_graph().draw_mermaid().strip())
        parts.append("```")
    parts.append(END_MARKER)
    return "\n".join(parts)


def main() -> None:
    text = README.read_text(encoding="utf-8")
    if START_MARKER not in text or END_MARKER not in text:
        raise SystemExit(
            f"README.md is missing {START_MARKER} / {END_MARKER} markers; nothing to replace."
        )
    before, rest = text.split(START_MARKER, 1)
    _, after = rest.split(END_MARKER, 1)
    README.write_text(before + render_block() + after, encoding="utf-8")
    print(f"Wrote {len(GRAPHS)} diagrams into {README}")


if __name__ == "__main__":
    main()
