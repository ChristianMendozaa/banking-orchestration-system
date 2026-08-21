from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import (
    CaseRecord,
    KioskSession,
    Requirement,
)
from app.db.repositories import CaseRepository
from app.domain.enums import (
    Category,
    Priority,
    ResolutionType,
    SessionStatus,
)
from app.domain.schemas import (
    ConfirmationRequest,
    ExecutiveAssignment,
    FlowResult,
    IdentificationRequest,
    KnowledgeCitation,
    SessionStatusResponse,
    TicketResult,
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
from app.services.pii import PIIMaskingService

# Deterministic, not model-authored -- matches how every other customer-facing sentence the
# kiosk speaks outside a grounded RAG answer is built (see _build_result below and
# _CUSTOMER_SUMMARIES in agents.py). A declined turn never reaches a confirmation step, so
# nothing here is generated per-request.
DECLINE_SPEECH_TEXT = (
    "En este kiosco solo puedo ayudarte con bloqueo de tarjetas, reporte de fraude, "
    "solicitudes de crédito, banca digital y consultas generales del banco. Para eso no te "
    "puedo ayudar aquí; si necesitas otra cosa, acércate con un ejecutivo en la sucursal."
)

# One short, deterministic reason per category, said before the ticket/desk/wait sentence in
# a human handoff -- so a person does not just hear a ticket number with no explanation of
# why they are being sent to a person. Kept separate from _CUSTOMER_SUMMARIES in agents.py:
# that one describes the customer's need in the confirmation step, this one frames the
# handoff itself.
_HANDOFF_REASONS = {
    Category.BLOQUEO_TARJETA: "Voy a derivarte con un ejecutivo para bloquear tu tarjeta.",
    Category.REPORTE_FRAUDE: (
        "Voy a derivarte con un ejecutivo de prevención de fraude para atender tu reporte."
    ),
    Category.CONSULTA_GENERAL: "Voy a derivarte con un ejecutivo para atender tu consulta.",
    Category.SOLICITUD_CREDITO: (
        "Voy a derivarte con un ejecutivo de créditos para continuar tu trámite."
    ),
    Category.BANCA_DIGITAL: (
        "Voy a derivarte con un ejecutivo de banca digital para resolver tu caso."
    ),
}
_URGENT_HANDOFF_REASSURANCE = " Este caso se está atendiendo como prioritario."

# Said after an answer the kiosk found by itself. A question resolved on the spot leaves the
# person still standing at the kiosk, and without this the conversation just stops -- which
# reads as being dismissed rather than answered.
_AUTOMATIC_FOLLOW_UP = "¿Te ayudo con algo más?"


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
            result = await self._build_result(db, kiosk_session.id)
            return self._completed_analysis_response(
                kiosk_session, final_state["requirement"], result
            )
        return self._analysis_response(final_state["kiosk_session"], final_state["requirement"])

    @staticmethod
    def _completed_analysis_response(
        kiosk_session: KioskSession, requirement: Requirement, result: FlowResult
    ) -> TurnAnalysisResponse:
        return TurnAnalysisResponse(
            requirement_id=requirement.id,
            status=kiosk_session.status,
            summary=requirement.summary,
            customer_summary=requirement.customer_summary,
            category=requirement.category,
            priority=requirement.proposed_priority,
            consultation_level=requirement.consultation_level,
            confidence=requirement.confidence,
            pii_types=requirement.pii_metadata.get("types", []),
            next_action="COMPLETE",
            speech_text=result.speech_text,
            result=result,
        )

    def _analysis_response(
        self, kiosk_session: KioskSession, requirement: Requirement
    ) -> TurnAnalysisResponse:
        if kiosk_session.status == SessionStatus.DECLINED:
            return TurnAnalysisResponse(
                requirement_id=requirement.id,
                status=SessionStatus.DECLINED,
                summary=requirement.summary,
                customer_summary=requirement.customer_summary,
                category=requirement.category,
                priority=requirement.proposed_priority,
                consultation_level=requirement.consultation_level,
                confidence=requirement.confidence,
                pii_types=requirement.pii_metadata.get("types", []),
                next_action="DECLINE",
                speech_text=DECLINE_SPEECH_TEXT,
            )
        clarify = kiosk_session.status == SessionStatus.NEEDS_CLARIFICATION
        question = requirement.clarification_question if clarify else None
        customer_summary = requirement.customer_summary.strip()
        confirmation_clause = customer_summary.rstrip(".?!")
        if confirmation_clause:
            confirmation_clause = confirmation_clause[0].lower() + confirmation_clause[1:]
        speech = question or f"¿Me confirmas si {confirmation_clause}?"
        return TurnAnalysisResponse(
            requirement_id=requirement.id,
            status=(
                SessionStatus.NEEDS_CLARIFICATION
                if clarify
                else SessionStatus.AWAITING_CONFIRMATION
            ),
            summary=requirement.summary,
            customer_summary=requirement.customer_summary,
            category=requirement.category,
            priority=requirement.proposed_priority,
            consultation_level=requirement.consultation_level,
            confidence=requirement.confidence,
            clarification_question=question,
            pii_types=requirement.pii_metadata.get("types", []),
            next_action="CLARIFY" if clarify else "CONFIRM",
            speech_text=speech,
        )

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

    @staticmethod
    def _capture_result(kiosk_session: KioskSession, requirement: Requirement) -> FlowResult:
        return FlowResult(
            session_id=kiosk_session.id,
            requirement_id=requirement.id,
            status=SessionStatus.LISTENING,
            next_action="CAPTURE",
            customer_summary=requirement.customer_summary,
            priority=requirement.proposed_priority,
            speech_text="Cuéntame nuevamente qué necesitas.",
        )

    @staticmethod
    def _identification_result(
        kiosk_session: KioskSession,
        case: CaseRecord,
        requirement: Requirement,
    ) -> FlowResult:
        return FlowResult(
            session_id=kiosk_session.id,
            requirement_id=case.requirement_id,
            status=SessionStatus.AWAITING_IDENTIFICATION,
            next_action="IDENTIFY",
            customer_summary=requirement.customer_summary,
            priority=requirement.proposed_priority,
            identification_status=case.identification_status,
            speech_text=(
                "Para continuar, escribe tu CI en el campo protegido. "
                "No escribas contraseñas, PIN ni datos financieros."
            ),
        )

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
        identification_graph terminal node sets into the matching pre-graph response
        helper. `BUILD_RESULT` covers both the pre-graph short-circuits that called
        `_build_result` directly and every path through the finalize subgraph, whose
        last node was always `return await self._build_result(...)`."""
        next_action = final_state["next_action"]
        kiosk_session = final_state["kiosk_session"]
        if next_action == "CAPTURE":
            return self._capture_result(kiosk_session, final_state["requirement"])
        if next_action == "IDENTIFY":
            return self._identification_result(
                kiosk_session, final_state["case"], final_state["requirement"]
            )
        return await self._build_result(db, kiosk_session.id)

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
                analysis = self._analysis_response(kiosk_session, requirement)
        elif kiosk_session.status == SessionStatus.AWAITING_IDENTIFICATION:
            case = await self.repository.case_by_session(
                db,
                kiosk_session.id,
                with_ticket=True,
            )
            if case and case.ticket:
                result = await self._build_result(db, kiosk_session.id)
            elif case:
                requirement = await db.get(Requirement, case.requirement_id)
                if requirement:
                    result = self._identification_result(
                        kiosk_session,
                        case,
                        requirement,
                    )
        elif kiosk_session.status in {
            SessionStatus.RESOLVED_AUTOMATIC,
            SessionStatus.ASSIGNED,
        }:
            result = await self._build_result(db, kiosk_session.id)

        return SessionStatusResponse(
            session_id=kiosk_session.id,
            status=kiosk_session.status,
            resolution_type=kiosk_session.resolution_type,
            final_response=kiosk_session.final_response,
            analysis=analysis,
            result=result,
        )

    async def _build_result(self, db: AsyncSession, session_id: UUID) -> FlowResult:
        ticket = await self.repository.result_ticket(db, session_id)
        if not ticket:
            raise AppError("RESULT_NOT_READY", "El resultado aun no esta disponible", 409)
        case = ticket.case
        requirement = await db.get(Requirement, case.requirement_id)
        if not requirement:
            raise AppError("REQUIREMENT_NOT_FOUND", "El requerimiento del caso no existe", 409)
        assignment = None
        if ticket.executive:
            assignment = ExecutiveAssignment(
                id=ticket.executive.id,
                name=ticket.executive.display_name,
                title=ticket.executive.title,
                window_number=ticket.executive.window_number,
            )
        automatic = case.session.resolution_type == ResolutionType.AUTOMATIC
        if automatic:
            answer = case.session.final_response or "Tu consulta quedó resuelta."
            speech = f"{answer} {_AUTOMATIC_FOLLOW_UP}"
        elif assignment:
            reason = _HANDOFF_REASONS.get(case.category, "")
            urgent = (
                _URGENT_HANDOFF_REASSURANCE
                if requirement.proposed_priority in {Priority.ALTO, Priority.CRITICO}
                else ""
            )
            wait_message = (
                f" La espera estimada es de {ticket.estimated_wait_minutes} minutos."
                if ticket.estimated_wait_minutes is not None
                else ""
            )
            speech = (
                f"{reason}{urgent} Tu ticket es {ticket.number}. Dirígete a "
                f"{assignment.window_number} con {assignment.name}.{wait_message}"
            )
        else:
            speech = f"Tu ticket es {ticket.number}. La asignación está pendiente."
        return FlowResult(
            session_id=session_id,
            requirement_id=case.requirement_id,
            status=case.session.status,
            next_action="COMPLETE",
            customer_summary=requirement.customer_summary,
            priority=requirement.proposed_priority,
            identification_status=case.identification_status,
            resolution_type=case.session.resolution_type,
            ticket=TicketResult(
                id=ticket.public_id,
                number=ticket.number,
                status=ticket.status,
                estimated_wait_minutes=ticket.estimated_wait_minutes,
            ),
            executive=assignment,
            response=case.session.final_response,
            speech_text=speech,
            # A closed automatic ticket is a record of the case, not something the person
            # asked for. Telling someone who wanted the branch hours to keep a reference
            # number reads as the conversation being over and as a queue they never joined.
            tracking_information=(
                None
                if automatic
                else (
                    f"Conserva el ticket {ticket.number}. "
                    f"{self.settings.support_tracking_information.strip()}"
                )
            ),
            grounding_status=case.session.grounding_status,
            citations=[
                KnowledgeCitation.model_validate(citation)
                for citation in case.session.citations_json
            ],
        )
