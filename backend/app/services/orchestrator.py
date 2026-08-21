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
    SpeechPlan,
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

# The written rendering of a declined turn, used by the text channel and as the voice
# channel's `fallback_text`. The voice channel no longer reads it aloud: it gets
# `_decline_plan()` below and words the refusal itself.
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


# The services the kiosk can actually attend. Named as a fact rather than a fixed sentence
# so the model can decline in its own words -- but it may not add to this list, which is why
# it is passed as data and repeated in the guidance.
_KIOSK_SCOPE = (
    "bloqueo de tarjetas, reporte de fraude, solicitudes de crédito, banca digital y "
    "consultas generales del banco"
)

# What belongs in `verbatim` and what belongs in `facts`.
#
# `verbatim` is checked by the client against what was actually spoken, so it can only hold
# strings that survive that comparison as text: the grounded answer, the credential warning,
# an executive's name, a window label. Numbers cannot go in it -- a model that says "tu
# ticket es el cuarenta y dos" has done nothing wrong, and a substring check on "42" would
# flag it and force a pointless re-read. The ticket number and the wait estimate therefore
# travel in `facts` with guidance to state them exactly, and the ticket screen stays the
# authoritative copy of both.


# Split so the warning half can travel in `verbatim` on its own: the instruction to use the
# protected field is a fact the model may reword, the prohibition is not.
_IDENTIFICATION_WARNING = "No escribas contraseñas, PIN ni datos financieros."
_IDENTIFICATION_SPEECH_TEXT = (
    f"Para continuar, escribe tu CI en el campo protegido. {_IDENTIFICATION_WARNING}"
)


def _decline_plan() -> SpeechPlan:
    return SpeechPlan(
        intent="DECLINE",
        facts={"alcance": _KIOSK_SCOPE},
        guidance=(
            "Dile con amabilidad que eso no lo puedes atender en este kiosco y nómbrale lo "
            "que sí atiendes, tomándolo de `alcance`. No ofrezcas ningún servicio que no "
            "esté en esa lista, no pidas confirmación y no sigas la conversación."
        ),
        fallback_text=DECLINE_SPEECH_TEXT,
    )


def _clarify_plan(question: str) -> SpeechPlan:
    return SpeechPlan(
        intent="CLARIFY",
        facts={"pregunta": question},
        guidance=(
            "Haz esa pregunta con tus palabras, en una sola frase breve y cordial. No "
            "preguntes nada más y no supongas la respuesta."
        ),
        fallback_text=question,
    )


def _confirm_plan(customer_summary: str, fallback_text: str) -> SpeechPlan:
    return SpeechPlan(
        intent="CONFIRM",
        facts={"entendido": customer_summary},
        guidance=(
            "Confirma en una pregunta breve y natural que entendiste eso. No agregues "
            "detalles que no estén en `entendido` y espera un sí o un no antes de seguir."
        ),
        fallback_text=fallback_text,
    )


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
            speech_plan=result.speech_plan,
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
                speech_plan=_decline_plan(),
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
            speech_plan=(
                _clarify_plan(question)
                if question
                else _confirm_plan(requirement.customer_summary, speech)
            ),
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
            speech_plan=SpeechPlan(
                intent="CAPTURE",
                guidance=(
                    "No entendiste bien lo que necesitaba. Pídele que te lo cuente otra "
                    "vez, con calma y sin disculparte de más. No repitas el resumen que "
                    "acaba de rechazar."
                ),
                fallback_text="Cuéntame nuevamente qué necesitas.",
            ),
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
            speech_text=_IDENTIFICATION_SPEECH_TEXT,
            speech_plan=SpeechPlan(
                intent="IDENTIFY",
                facts={"accion": "escribir su CI en el campo protegido de la pantalla"},
                verbatim=[_IDENTIFICATION_WARNING],
                guidance=(
                    "Pídele que haga lo que dice `accion` y repite la advertencia de "
                    "`verbatim` palabra por palabra. Nunca le pidas que dicte el CI en voz "
                    "alta. Luego deja de hacer preguntas mientras escribe."
                ),
                fallback_text=_IDENTIFICATION_SPEECH_TEXT,
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
        urgent_case = requirement.proposed_priority in {Priority.ALTO, Priority.CRITICO}
        if case.session.resolution_type == ResolutionType.AUTOMATIC:
            speech = case.session.final_response or "Tu consulta quedó resuelta."
            plan = SpeechPlan(
                intent="ANSWER",
                # The answer is bound to the retrieved evidence and was already checked
                # against it (`GroundedAnswerDecision.supported`). Rewording it would break
                # that binding, so it is the one long string the model must reproduce.
                verbatim=[speech],
                guidance=(
                    "Entrega la respuesta de `verbatim` tal cual, completa y sin resumirla "
                    "ni agregarle datos. Puedes presentarla y cerrarla con tus palabras. "
                    "Después pregúntale si necesita algo más y sigue escuchando."
                ),
                fallback_text=speech,
            )
        elif assignment:
            reason = _HANDOFF_REASONS.get(case.category, "")
            urgent = _URGENT_HANDOFF_REASSURANCE if urgent_case else ""
            wait_message = (
                f" La espera estimada es de {ticket.estimated_wait_minutes} minutos."
                if ticket.estimated_wait_minutes is not None
                else ""
            )
            speech = (
                f"{reason}{urgent} Tu ticket es {ticket.number}. Dirígete a "
                f"{assignment.window_number} con {assignment.name}.{wait_message}"
            )
            facts = {
                "motivo": reason,
                "ticket": str(ticket.number),
                "ventanilla": assignment.window_number,
                "ejecutivo": assignment.name,
            }
            if ticket.estimated_wait_minutes is not None:
                facts["espera_minutos"] = str(ticket.estimated_wait_minutes)
            if urgent_case:
                facts["prioritario"] = "sí"
            plan = SpeechPlan(
                intent="HANDOFF",
                facts=facts,
                verbatim=[assignment.window_number, assignment.name],
                guidance=(
                    "Explícale con tus palabras por qué lo derivas, usando `motivo`, y "
                    "dale el número de ticket, la ventanilla y el nombre del ejecutivo "
                    "exactamente como aparecen en `facts`. Si hay `espera_minutos`, "
                    "menciónalo. Si hay `prioritario`, dile que su caso se atiende como "
                    "prioritario. Despídete: a partir de aquí lo atiende una persona."
                ),
                fallback_text=speech,
            )
        else:
            speech = f"Tu ticket es {ticket.number}. La asignación está pendiente."
            plan = SpeechPlan(
                intent="HANDOFF",
                facts={"ticket": str(ticket.number), "asignacion": "pendiente"},
                guidance=(
                    "Dale el número de ticket exactamente como aparece y explícale que "
                    "todavía no hay una ventanilla asignada, que espere a que lo llamen. "
                    "No inventes un ejecutivo ni una ventanilla."
                ),
                fallback_text=speech,
            )
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
            speech_plan=plan,
            tracking_information=(
                f"Conserva el ticket {ticket.number}. "
                f"{self.settings.support_tracking_information.strip()}"
            ),
            grounding_status=case.session.grounding_status,
            citations=[
                KnowledgeCitation.model_validate(citation)
                for citation in case.session.citations_json
            ],
        )
