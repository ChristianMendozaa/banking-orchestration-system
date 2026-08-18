"""Shared state and runtime-context shapes for the kiosk orchestration graphs.

Architecture note: these graphs are compiled WITHOUT a checkpointer (see `builder.py`).
Each customer turn is already a separate HTTP request, so the request boundary is the
"pause" -- a LangGraph checkpointer + `interrupt()` would duplicate state `SessionStatus`
already owns, and would create a second source of truth that commits in a different
transaction than the SQLAlchemy row it must stay consistent with. See the architecture
plan (Decision 1) for the full reasoning.

Because there is no checkpointer, state is never serialized, so `OrchestrationState`
carries live SQLAlchemy ORM row objects directly (the same objects the pre-graph
`OrchestratorService` methods already passed to each other as plain arguments) rather
than IDs the nodes would have to re-fetch. If a checkpointer is ever introduced, this
state shape must be redesigned around IDs first -- do not add one without revisiting
this file.

`GraphContext` is the one and only place a live `AsyncSession` may live. It is injected
via LangGraph's `Runtime[GraphContext]`, never placed in state.
"""

from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import CaseRecord, KioskSession, Requirement, Ticket
from app.db.repositories import CaseRepository
from app.domain.enums import IdentificationStatus
from app.domain.schemas import (
    ClassificationDecision,
    ConfirmationRequest,
    GroundedResponse,
    IdentificationRequest,
    TurnRequest,
)
from app.services.agents import (
    ClassificationAgent,
    DerivationAgent,
    InitialAttentionAgent,
    PrioritizationAgent,
)
from app.services.pii import PIIMaskingService


@dataclass(slots=True)
class GraphContext:
    db: AsyncSession
    settings: Settings
    repository: CaseRepository
    pii: PIIMaskingService
    classifier: ClassificationAgent
    prioritizer: PrioritizationAgent
    derivation: DerivationAgent
    initial_attention: InitialAttentionAgent


class OrchestrationState(TypedDict, total=False):
    # Always present at graph entry.
    kiosk_session: KioskSession

    # Entry payloads, one per graph.
    turn_payload: TurnRequest
    confirmation_payload: ConfirmationRequest
    identification_payload: IdentificationRequest

    # turn_graph working state.
    masked_context: str
    pii_metadata: dict
    decision: ClassificationDecision
    classification_source: str
    force_human: bool
    auto_resolve: bool

    # Shared across graphs once known.
    requirement: Requirement
    case: CaseRecord | None

    # Set by every confirmation_graph / identification_graph terminal node; tells the
    # OrchestratorService adapter which existing response-shaping helper to call after
    # ainvoke() returns (_capture_result / _identification_result / _build_result). The
    # graphs only perform state transitions; response shaping stays plain Python, exactly
    # as it was pre-graph -- see builder.py module docstring.
    next_action: str

    # identification_graph working state.
    identifier_hash: str
    client_reference_id: UUID | None
    identification_result_status: IdentificationStatus

    # finalize subgraph working state.
    grounded_response: GroundedResponse | None
    grounding_attempted: bool
    ticket: Ticket
