"""The orchestrator service: a thin adapter over the LangGraph graphs.

It does four things and nothing else -- lock the session row, invoke the graph for the
entry point that was called, resolve the `next_action` marker its terminal node set into
the matching response helper, and report session status.

The state machine itself lives in `app.services.graph`; response shaping lives in
`app.services.orchestrator.responses`; every sentence the kiosk says lives in
`app.services.orchestrator.speech`.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import KioskSession, Requirement
from app.db.repositories import CaseRepository
from app.domain.enums import SessionStatus
from app.domain.schemas import (
    ConfirmationRequest,
    FlowResult,
    IdentificationRequest,
    SessionStatusResponse,
    TurnAnalysisResponse,
    TurnRequest,
)
from app.services.agents import (
    ClassificationAgent,
    DerivationAgent,
    InitialAttentionAgent,
    PrioritizationAgent,
)
from app.services.graph.builder import confirmation_graph, identification_graph, turn_graph
from app.services.graph.state import GraphContext
from app.services.orchestrator.responses import (
    analysis_response,
    build_result,
    capture_result,
    completed_analysis_response,
    identification_result,
)
from app.services.pii import PIIMaskingService


class OrchestratorService:
    def __init__(
        self,
        settings: Settings,
        pii: PIIMaskingService,
        classifier: ClassificationAgent,
        prioritizer: PrioritizationAgent,
        derivation: DerivationAgent,
        initial_attention: InitialAttentionAgent,
        repository: CaseRepository | None = None,
    ) -> None:
        self.settings = settings
        self.pii = pii
        self.classifier = classifier
        self.prioritizer = prioritizer
        self.derivation = derivation
        self.initial_attention = initial_attention
        self.repository = repository or CaseRepository()

    def _graph_context(self, db: AsyncSession) -> GraphContext:
        return GraphContext(
            db=db,
            settings=self.settings,
            repository=self.repository,
            pii=self.pii,
            classifier=self.classifier,
            prioritizer=self.prioritizer,
            derivation=self.derivation,
            initial_attention=self.initial_attention,
        )

    async def analyze_turn(
        self, db: AsyncSession, kiosk_session: KioskSession, payload: TurnRequest
    ) -> TurnAnalysisResponse:
        kiosk_session = await self._lock_session(db, kiosk_session.id)
        final_state = await turn_graph.ainvoke(
            {"kiosk_session": kiosk_session, "turn_payload": payload},
            context=self._graph_context(db),
        )
        # Set only when a confident GENERAL classification skipped confirmation and ran
        # straight through the shared finalize subgraph (turn_nodes.auto_capture) or when
        # guard_turn replayed an already-resolved turn_id -- every other path here still
        # ends in NEEDS_CLARIFICATION / AWAITING_CONFIRMATION / DECLINED, handled below.
        if final_state.get("next_action") == "BUILD_RESULT":
            result = await build_result(db, kiosk_session.id, self.repository, self.settings)
            return completed_analysis_response(kiosk_session, final_state["requirement"], result)
        return analysis_response(final_state["kiosk_session"], final_state["requirement"])

    async def _lock_session(self, db: AsyncSession, session_id: UUID) -> KioskSession:
        statement = (
            select(KioskSession)
            .where(KioskSession.id == session_id)
            .execution_options(populate_existing=True)
        )
        if db.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        kiosk_session = await db.scalar(statement)
        if not kiosk_session:
            raise AppError("SESSION_NOT_FOUND", "La sesión ya no está disponible", 404)
        return kiosk_session

    async def confirm(
        self,
        db: AsyncSession,
        kiosk_session: KioskSession,
        payload: ConfirmationRequest,
    ) -> FlowResult:
        kiosk_session = await self._lock_session(db, kiosk_session.id)
        final_state = await confirmation_graph.ainvoke(
            {"kiosk_session": kiosk_session, "confirmation_payload": payload},
            context=self._graph_context(db),
        )
        return await self._dispatch_result(db, final_state)

    async def identify(
        self, db: AsyncSession, kiosk_session: KioskSession, payload: IdentificationRequest
    ) -> FlowResult:
        kiosk_session = await self._lock_session(db, kiosk_session.id)
        final_state = await identification_graph.ainvoke(
            {"kiosk_session": kiosk_session, "identification_payload": payload},
            context=self._graph_context(db),
        )
        return await self._dispatch_result(db, final_state)

    async def _dispatch_result(self, db: AsyncSession, final_state: dict) -> FlowResult:
        """Resolves the `next_action` marker every confirmation_graph /
        identification_graph terminal node sets into the matching helper in
        `responses`. `BUILD_RESULT` covers both the short-circuits that reach a finished
        ticket directly and every path through the finalize subgraph, whose last node
        always ended in that same call."""
        next_action = final_state["next_action"]
        kiosk_session = final_state["kiosk_session"]
        if next_action == "CAPTURE":
            return capture_result(kiosk_session, final_state["requirement"])
        if next_action == "IDENTIFY":
            return identification_result(
                kiosk_session, final_state["case"], final_state["requirement"]
            )
        return await build_result(db, kiosk_session.id, self.repository, self.settings)

    async def build_session_status(
        self, db: AsyncSession, kiosk_session: KioskSession
    ) -> SessionStatusResponse:
        analysis = None
        result = None
        if kiosk_session.status in {
            SessionStatus.NEEDS_CLARIFICATION,
            SessionStatus.AWAITING_CONFIRMATION,
            SessionStatus.DECLINED,
        }:
            requirement = await self.repository.latest_requirement(db, kiosk_session.id)
            if requirement:
                analysis = analysis_response(kiosk_session, requirement)
        elif kiosk_session.status == SessionStatus.AWAITING_IDENTIFICATION:
            case = await self.repository.case_by_session(
                db,
                kiosk_session.id,
                with_ticket=True,
            )
            if case and case.ticket:
                result = await build_result(db, kiosk_session.id, self.repository, self.settings)
            elif case:
                requirement = await db.get(Requirement, case.requirement_id)
                if requirement:
                    result = identification_result(
                        kiosk_session,
                        case,
                        requirement,
                    )
        elif kiosk_session.status in {
            SessionStatus.RESOLVED_AUTOMATIC,
            SessionStatus.ASSIGNED,
        }:
            result = await build_result(db, kiosk_session.id, self.repository, self.settings)

        return SessionStatusResponse(
            session_id=kiosk_session.id,
            status=kiosk_session.status,
            resolution_type=kiosk_session.resolution_type,
            final_response=kiosk_session.final_response,
            analysis=analysis,
            result=result,
        )
