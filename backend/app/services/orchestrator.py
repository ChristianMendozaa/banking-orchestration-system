from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_identifier, mask_identifier
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
    ExecutiveAssignment,
    FlowResult,
    IdentificationRequest,
    KnowledgeCitation,
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
        existing = await self.repository.requirement_by_turn(db, kiosk_session.id, payload.turn_id)
        if existing:
            return self._analysis_response(kiosk_session, existing)
        if kiosk_session.status == SessionStatus.AWAITING_CONFIRMATION:
            pending = await self.repository.latest_requirement(db, kiosk_session.id)
            if pending:
                return self._analysis_response(kiosk_session, pending)

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

        decision = await self.classifier.run(context)
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
            category=decision.category,
            proposed_priority=proposed_priority,
            consultation_level=decision.consultation_level,
            confidence=decision.confidence,
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
        speech = question or f"Entendi lo siguiente: {requirement.summary}. ¿Es correcto?"
        return TurnAnalysisResponse(
            requirement_id=requirement.id,
            status=kiosk_session.status,
            summary=requirement.summary,
            category=requirement.category,
            priority=requirement.proposed_priority,
            consultation_level=requirement.consultation_level,
            confidence=requirement.confidence,
            clarification_question=question,
            pii_types=requirement.pii_metadata.get("types", []),
            next_action="CLARIFY" if clarify else "CONFIRM",
            speech_text=speech,
        )

    async def confirm(
        self, db: AsyncSession, kiosk_session: KioskSession, confirmed: bool
    ) -> FlowResult:
        if kiosk_session.status in {
            SessionStatus.RESOLVED_AUTOMATIC,
            SessionStatus.ASSIGNED,
        }:
            return await self._build_result(db, kiosk_session.id)
        if kiosk_session.status != SessionStatus.AWAITING_CONFIRMATION:
            raise AppError(
                "INVALID_SESSION_STATE",
                "La sesion no tiene un requerimiento pendiente de confirmacion",
                409,
                {"status": kiosk_session.status.value},
            )
        requirement = await self.repository.latest_requirement(db, kiosk_session.id)
        if not requirement:
            raise AppError(
                "REQUIREMENT_NOT_FOUND", "No existe un requerimiento para confirmar", 409
            )
        if requirement.ambiguous:
            raise AppError(
                "CLARIFICATION_REQUIRED", "Debe responder la pregunta de aclaracion", 409
            )

        if not confirmed:
            requirement.active = False
            kiosk_session.correction_count += 1
            kiosk_session.status = SessionStatus.LISTENING
            return FlowResult(
                session_id=kiosk_session.id,
                status=kiosk_session.status,
                next_action="CAPTURE",
                speech_text="Puede describir nuevamente su requerimiento.",
            )

        case = await self.repository.case_by_session(db, kiosk_session.id, with_ticket=True)
        if case and case.ticket:
            return await self._build_result(db, kiosk_session.id)
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
                        description="Requerimiento capturado y confirmado por el cliente",
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
                        metadata_json={"confidence": requirement.confidence},
                    ),
                ]
            )

        if case.identification_status == IdentificationStatus.PENDIENTE:
            kiosk_session.status = SessionStatus.AWAITING_IDENTIFICATION
            return FlowResult(
                session_id=kiosk_session.id,
                status=kiosk_session.status,
                next_action="IDENTIFY",
                identification_status=case.identification_status,
                speech_text=(
                    "Esta consulta requiere verificar su codigo de cliente en el campo protegido. "
                    "No ingrese contrasenas, PIN ni datos financieros."
                ),
            )
        return await self._finalize(db, kiosk_session, case)

    async def identify(
        self, db: AsyncSession, kiosk_session: KioskSession, payload: IdentificationRequest
    ) -> FlowResult:
        if kiosk_session.status in {
            SessionStatus.RESOLVED_AUTOMATIC,
            SessionStatus.ASSIGNED,
        }:
            return await self._build_result(db, kiosk_session.id)
        if kiosk_session.status != SessionStatus.AWAITING_IDENTIFICATION:
            raise AppError(
                "INVALID_SESSION_STATE",
                "La sesion no espera una identificacion",
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
            raise AppError("CASE_NOT_FOUND", "Primero debe confirmar el requerimiento", 409)
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
        if case.identification:
            case.identification.client_reference_id = (
                client_reference.id if client_reference else None
            )
            case.identification.identifier_hash = identifier_hash
            case.identification.masked_identifier = mask_identifier(payload.identifier)
            case.identification.status = status
        else:
            db.add(
                Identification(
                    case_id=case.id,
                    client_reference_id=client_reference.id if client_reference else None,
                    identifier_hash=identifier_hash,
                    masked_identifier=mask_identifier(payload.identifier),
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
            case.status = CaseStatus.ASSIGNED
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

    async def _build_result(self, db: AsyncSession, session_id: UUID) -> FlowResult:
        ticket = await self.repository.result_ticket(db, session_id)
        if not ticket:
            raise AppError("RESULT_NOT_READY", "El resultado aun no esta disponible", 409)
        case = ticket.case
        assignment = None
        if ticket.executive:
            assignment = ExecutiveAssignment(
                id=ticket.executive.id,
                name=ticket.executive.display_name,
                title=ticket.executive.title,
                window_number=ticket.executive.window_number,
            )
        if case.session.resolution_type == ResolutionType.AUTOMATIC:
            speech = case.session.final_response or "La consulta fue resuelta."
        elif assignment:
            wait_message = (
                f" La espera estimada es de {ticket.estimated_wait_minutes} minutos."
                if ticket.estimated_wait_minutes is not None
                else ""
            )
            speech = (
                f"Su ticket es {ticket.number}. Dirijase a {assignment.window_number} "
                f"con {assignment.name}.{wait_message}"
            )
        else:
            speech = f"Su ticket es {ticket.number}. La asignacion esta pendiente."
        return FlowResult(
            session_id=session_id,
            status=case.session.status,
            next_action="COMPLETE",
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
                f"Conserve el ticket {ticket.number}. Para seguimiento o reclamos puede "
                "comunicarse a la Linea Movil 788-12000, disponible las 24 horas, o a la "
                "linea gratuita 800-17-0777 de lunes a sabado, de 09:00 a 18:00."
            ),
            grounding_status=case.session.grounding_status,
            citations=[
                KnowledgeCitation.model_validate(citation)
                for citation in case.session.citations_json
            ],
        )
