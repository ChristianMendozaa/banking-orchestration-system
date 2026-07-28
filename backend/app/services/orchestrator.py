from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import encrypt_identifier, hash_identifier, mask_identifier
from app.db.models import (
    CaseRecord,
    ClientReference,
    Identification,
    KioskSession,
    Requirement,
    Ticket,
    TraceEvent,
)
from app.db.repositories import CaseRepository
from app.domain.enums import (
    CaseStatus,
    Category,
    ConsultationLevel,
    GroundingStatus,
    IdentificationStatus,
    ResolutionType,
    SessionStatus,
    TicketStatus,
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

    async def analyze_turn(
        self, db: AsyncSession, kiosk_session: KioskSession, payload: TurnRequest
    ) -> TurnAnalysisResponse:
        kiosk_session = await self._lock_session(db, kiosk_session.id)
        existing = await self.repository.requirement_by_turn(db, kiosk_session.id, payload.turn_id)
        if kiosk_session.status == SessionStatus.AWAITING_CONFIRMATION or (
            kiosk_session.status == SessionStatus.NEEDS_CLARIFICATION and existing
        ):
            pending = await self.repository.latest_requirement(db, kiosk_session.id)
            if pending:
                return self._analysis_response(kiosk_session, pending)
        if existing:
            raise AppError(
                "TURN_ALREADY_COMPLETED",
                "Ese turno ya fue procesado y el flujo avanzó",
                409,
                {"status": kiosk_session.status.value},
            )

        allowed_statuses = {
            SessionStatus.CREATED,
            SessionStatus.LISTENING,
            SessionStatus.NEEDS_CLARIFICATION,
        }
        if kiosk_session.status not in allowed_statuses:
            raise AppError(
                "INVALID_SESSION_STATE",
                "La sesion no admite un nuevo turno en su estado actual",
                409,
                {"status": kiosk_session.status.value},
            )
        if payload.is_clarification != (kiosk_session.status == SessionStatus.NEEDS_CLARIFICATION):
            raise AppError(
                "INVALID_CLARIFICATION",
                "El indicador de aclaracion no coincide con el estado de la sesion",
                409,
            )

        masked = self.pii.mask(payload.transcript)
        context = masked.masked_text
        if payload.is_clarification:
            previous = await self.repository.latest_requirement(db, kiosk_session.id)
            if previous:
                context = f"{previous.masked_text}\nAclaracion: {masked.masked_text}"
                previous.active = False

        decision, classification_source = await self.classifier.run_with_source(context)
        force_human = False
        needs_clarification = (
            decision.ambiguous
            or decision.confidence < self.settings.classification_confidence_threshold
        )
        if (
            needs_clarification
            and kiosk_session.clarification_count < self.settings.max_clarifications
        ):
            kiosk_session.clarification_count += 1
            kiosk_session.status = SessionStatus.NEEDS_CLARIFICATION
        elif needs_clarification:
            decision = decision.model_copy(
                update={
                    "summary": context[:500],
                    "category": Category.CONSULTA_GENERAL,
                    "consultation_level": ConsultationLevel.GENERAL,
                    "ambiguous": False,
                    "clarification_question": None,
                    "confidence": max(decision.confidence, 0.5),
                }
            )
            force_human = True
            kiosk_session.status = SessionStatus.AWAITING_CONFIRMATION
        else:
            kiosk_session.status = SessionStatus.AWAITING_CONFIRMATION

        proposed_priority = self.prioritizer.run(
            decision.category,
            decision.summary,
            kiosk_session.preferential_attention,
            urgency_detected=decision.urgency_detected,
            security_incident=decision.security_incident,
            distress_detected=decision.distress_detected,
        )
        requirement = Requirement(
            session_id=kiosk_session.id,
            turn_id=payload.turn_id,
            masked_text=context,
            pii_metadata={"types": masked.pii_types, "counts": masked.counts},
            summary=decision.summary,
            customer_summary=decision.customer_summary,
            category=decision.category,
            proposed_priority=proposed_priority,
            consultation_level=decision.consultation_level,
            confidence=decision.confidence,
            classification_source=classification_source,
            ambiguous=kiosk_session.status == SessionStatus.NEEDS_CLARIFICATION,
            clarification_question=decision.clarification_question,
            force_human=force_human,
            urgency_detected=decision.urgency_detected,
            security_incident=decision.security_incident,
            distress_detected=decision.distress_detected,
        )
        db.add(requirement)
        await db.flush()
        return self._analysis_response(kiosk_session, requirement)

    def _analysis_response(
        self, kiosk_session: KioskSession, requirement: Requirement
    ) -> TurnAnalysisResponse:
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
        requirement = await db.scalar(
            select(Requirement).where(
                Requirement.id == payload.requirement_id,
                Requirement.session_id == kiosk_session.id,
            )
        )
        if not requirement:
            raise AppError(
                "REQUIREMENT_NOT_FOUND",
                "No encontramos el requerimiento que intentas confirmar",
                409,
            )

        case = await self.repository.case_by_session(db, kiosk_session.id, with_ticket=True)
        if case and case.requirement_id != requirement.id:
            raise AppError(
                "REQUIREMENT_MISMATCH",
                "La confirmación corresponde a un requerimiento anterior",
                409,
            )

        if requirement.confirmation_decision is None:
            if case:
                requirement.confirmation_decision = True
            elif not requirement.active and not requirement.ambiguous:
                requirement.confirmation_decision = False

        if requirement.confirmation_decision is not None:
            if requirement.confirmation_decision != payload.confirmed:
                raise AppError(
                    "CONFIRMATION_ALREADY_RECORDED",
                    "La confirmación ya fue registrada con otra respuesta",
                    409,
                )
            if not payload.confirmed:
                if kiosk_session.status != SessionStatus.LISTENING:
                    raise AppError(
                        "REQUIREMENT_MISMATCH",
                        "La confirmación corresponde a un requerimiento anterior",
                        409,
                    )
                return self._capture_result(kiosk_session, requirement)
            if case and case.ticket:
                return await self._build_result(db, kiosk_session.id)
            if case and case.identification_status == IdentificationStatus.PENDIENTE:
                kiosk_session.status = SessionStatus.AWAITING_IDENTIFICATION
                return self._identification_result(kiosk_session, case, requirement)
            if case:
                return await self._finalize(db, kiosk_session, case)

        if kiosk_session.status in {
            SessionStatus.RESOLVED_AUTOMATIC,
            SessionStatus.ASSIGNED,
        }:
            return await self._build_result(db, kiosk_session.id)
        if kiosk_session.status != SessionStatus.AWAITING_CONFIRMATION:
            raise AppError(
                "INVALID_SESSION_STATE",
                "La sesión no tiene un requerimiento pendiente de confirmación",
                409,
                {"status": kiosk_session.status.value},
            )
        pending = await self.repository.latest_requirement(db, kiosk_session.id)
        if not pending or pending.id != requirement.id:
            raise AppError(
                "REQUIREMENT_MISMATCH",
                "La confirmación corresponde a un requerimiento anterior",
                409,
            )
        if requirement.ambiguous:
            raise AppError(
                "CLARIFICATION_REQUIRED",
                "Primero responde la pregunta de aclaración",
                409,
            )

        requirement.confirmation_decision = payload.confirmed
        if not payload.confirmed:
            requirement.active = False
            kiosk_session.correction_count += 1
            kiosk_session.status = SessionStatus.LISTENING
            return self._capture_result(kiosk_session, requirement)

        if not case:
            identification_status = (
                IdentificationStatus.ANONIMO
                if requirement.consultation_level == ConsultationLevel.GENERAL
                else IdentificationStatus.PENDIENTE
            )
            case = CaseRecord(
                session_id=kiosk_session.id,
                requirement_id=requirement.id,
                category=requirement.category,
                consultation_level=requirement.consultation_level,
                identification_status=identification_status,
                summary=requirement.summary,
                preferential_attention=kiosk_session.preferential_attention,
                status=CaseStatus.CLASSIFIED,
                force_human=requirement.force_human,
            )
            db.add(case)
            await db.flush()
            db.add_all(
                [
                    TraceEvent(
                        case_id=case.id,
                        event_type="REQUIREMENT_CAPTURED",
                        description="Requerimiento capturado y confirmado",
                    ),
                    TraceEvent(
                        case_id=case.id,
                        event_type="PII_MASKED",
                        description="Datos sensibles enmascarados antes del procesamiento interno",
                        metadata_json={"pii_types": requirement.pii_metadata.get("types", [])},
                    ),
                    TraceEvent(
                        case_id=case.id,
                        event_type="CASE_CLASSIFIED",
                        description=f"Caso clasificado como {case.category.value}",
                        metadata_json={
                            "confidence": requirement.confidence,
                            "source": requirement.classification_source,
                        },
                    ),
                ]
            )

        if case.identification_status == IdentificationStatus.PENDIENTE:
            kiosk_session.status = SessionStatus.AWAITING_IDENTIFICATION
            return self._identification_result(kiosk_session, case, requirement)
        return await self._finalize(db, kiosk_session, case)

    async def identify(
        self, db: AsyncSession, kiosk_session: KioskSession, payload: IdentificationRequest
    ) -> FlowResult:
        kiosk_session = await self._lock_session(db, kiosk_session.id)
        if kiosk_session.status in {
            SessionStatus.RESOLVED_AUTOMATIC,
            SessionStatus.ASSIGNED,
        }:
            return await self._build_result(db, kiosk_session.id)
        if kiosk_session.status != SessionStatus.AWAITING_IDENTIFICATION:
            raise AppError(
                "INVALID_SESSION_STATE",
                "La sesión no espera un CI",
                409,
                {"status": kiosk_session.status.value},
            )
        case = await self.repository.case_by_session(
            db,
            kiosk_session.id,
            with_identification=True,
            with_ticket=True,
        )
        if not case:
            raise AppError("CASE_NOT_FOUND", "Primero confirma el requerimiento", 409)
        if case.ticket:
            return await self._build_result(db, kiosk_session.id)

        identifier_hash = hash_identifier(payload.identifier, self.settings)
        client_reference = await db.scalar(
            select(ClientReference).where(
                ClientReference.identifier_hash == identifier_hash,
                ClientReference.active.is_(True),
            )
        )
        status = (
            IdentificationStatus.IDENTIFICADO if client_reference else IdentificationStatus.FALLIDO
        )
        ciphertext, nonce, key_id = encrypt_identifier(
            payload.identifier,
            str(case.id),
            self.settings,
        )
        if case.identification:
            case.identification.client_reference_id = (
                client_reference.id if client_reference else None
            )
            case.identification.identifier_hash = identifier_hash
            case.identification.masked_identifier = mask_identifier(payload.identifier)
            case.identification.identifier_ciphertext = ciphertext
            case.identification.identifier_nonce = nonce
            case.identification.identifier_key_id = key_id
            case.identification.status = status
        else:
            db.add(
                Identification(
                    case_id=case.id,
                    client_reference_id=client_reference.id if client_reference else None,
                    identifier_hash=identifier_hash,
                    masked_identifier=mask_identifier(payload.identifier),
                    identifier_ciphertext=ciphertext,
                    identifier_nonce=nonce,
                    identifier_key_id=key_id,
                    status=status,
                )
            )
        case.identification_status = status
        db.add(
            TraceEvent(
                case_id=case.id,
                event_type="CLIENT_IDENTIFICATION",
                description=f"Identificacion de cliente: {status.value}",
            )
        )
        return await self._finalize(db, kiosk_session, case)

    async def _finalize(
        self, db: AsyncSession, kiosk_session: KioskSession, case: CaseRecord
    ) -> FlowResult:
        existing = await self.repository.ticket_by_case(db, case.id)
        if existing:
            return await self._build_result(db, kiosk_session.id)

        kiosk_session.status = SessionStatus.ORCHESTRATING
        case.status = CaseStatus.ORCHESTRATING
        requirement = await db.get(Requirement, case.requirement_id)
        if not requirement:
            raise AppError("REQUIREMENT_NOT_FOUND", "El requerimiento del caso no existe", 409)
        priority = requirement.proposed_priority
        case.priority = priority
        db.add(
            TraceEvent(
                case_id=case.id,
                event_type="PRIORITY_ASSIGNED",
                description=f"Prioridad asignada: {priority.value}",
            )
        )

        grounded_response = None
        if not case.force_human:
            grounded_response = await self.initial_attention.run(
                db,
                case.id,
                case.category,
                case.consultation_level,
                requirement.masked_text,
            )

        now = datetime.now(UTC)
        if grounded_response:
            ticket = Ticket(
                public_id=uuid4(),
                case_id=case.id,
                automatic=True,
                status=TicketStatus.CERRADO,
                assigned_at=now,
                estimated_wait_minutes=0,
                started_at=now,
                closed_at=now,
            )
            case.status = CaseStatus.RESOLVED
            kiosk_session.status = SessionStatus.RESOLVED_AUTOMATIC
            kiosk_session.resolution_type = ResolutionType.AUTOMATIC
            kiosk_session.final_response = grounded_response.answer
            kiosk_session.grounding_status = GroundingStatus.GROUNDED
            kiosk_session.citations_json = [
                citation.model_dump(mode="json") for citation in grounded_response.citations
            ]
            db.add(
                TraceEvent(
                    case_id=case.id,
                    event_type="AUTOMATIC_RESPONSE",
                    description="Consulta general resuelta con evidencia documental",
                    metadata_json={"citations": kiosk_session.citations_json},
                )
            )
        else:
            kiosk_session.grounding_status = (
                GroundingStatus.NO_EVIDENCE
                if case.category == Category.CONSULTA_GENERAL
                and case.consultation_level == ConsultationLevel.GENERAL
                and not case.force_human
                else GroundingStatus.NOT_APPLICABLE
            )
            kiosk_session.citations_json = []
            routing = await self.derivation.run(db, case.category, case.summary)
            executive = routing.executive if routing else None
            estimated_wait = (
                (routing.active_load + 1) * self.settings.estimated_service_minutes
                if routing
                else None
            )
            ticket = Ticket(
                public_id=uuid4(),
                case_id=case.id,
                executive_id=executive.id if executive else None,
                automatic=False,
                status=TicketStatus.PENDIENTE,
                assigned_at=now if executive else None,
                estimated_wait_minutes=estimated_wait,
            )
            if executive:
                executive.last_assigned_at = now
                description = f"Caso derivado a {executive.display_name}"
            else:
                description = "Caso pendiente de asignacion por falta de ejecutivo disponible"
            case.status = CaseStatus.ASSIGNED if executive else CaseStatus.QUEUED
            kiosk_session.status = SessionStatus.ASSIGNED
            kiosk_session.resolution_type = ResolutionType.HUMAN
            db.add(
                TraceEvent(
                    case_id=case.id,
                    event_type="CASE_ROUTED",
                    description=description,
                    metadata_json=(
                        {
                            "score": round(routing.score, 4),
                            "semantic_score": round(routing.semantic_score, 4),
                            "experience_score": round(routing.experience_score, 4),
                            "load_score": round(routing.load_score, 4),
                            "active_load": routing.active_load,
                            "estimated_wait_minutes": estimated_wait,
                        }
                        if routing
                        else {"estimated_wait_minutes": None}
                    ),
                )
            )
        db.add(ticket)
        await db.flush()
        return await self._build_result(db, kiosk_session.id)

    async def build_session_status(
        self, db: AsyncSession, kiosk_session: KioskSession
    ) -> SessionStatusResponse:
        analysis = None
        result = None
        if kiosk_session.status in {
            SessionStatus.NEEDS_CLARIFICATION,
            SessionStatus.AWAITING_CONFIRMATION,
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
        if case.session.resolution_type == ResolutionType.AUTOMATIC:
            speech = case.session.final_response or "Tu consulta quedó resuelta."
        elif assignment:
            wait_message = (
                f" La espera estimada es de {ticket.estimated_wait_minutes} minutos."
                if ticket.estimated_wait_minutes is not None
                else ""
            )
            speech = (
                f"Tu ticket es {ticket.number}. Dirígete a {assignment.window_number} "
                f"con {assignment.name}.{wait_message}"
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
