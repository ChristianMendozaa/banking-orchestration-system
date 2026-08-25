"""Finalize every independent case in one intake plan.

The primary case is driven interactively by the public graph. This coordinator materializes
the remaining planned cases through the same identification and finalize implementations,
then restores the session projection to the primary outcome.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import CaseRecord, KioskSession, Requirement
from app.domain.enums import ConsultationLevel, ResolutionType, SessionStatus
from app.domain.schemas import IdentificationRequest
from app.services.graph import confirmation_nodes
from app.services.graph.builder import finalize_subgraph
from app.services.graph.identification_nodes import record_identification, resolve_identifier
from app.services.graph.state import GraphContext


class OutcomeCoordinator:
    async def finalize_plan(
        self,
        db: AsyncSession,
        kiosk_session: KioskSession,
        primary: Requirement,
        context: GraphContext,
        *,
        identifier_payload: IdentificationRequest | None,
    ) -> None:
        requirements = await context.repository.requirements_for_turn(
            db, kiosk_session.id, primary.turn_id
        )
        if len(requirements) == 1:
            return

        for requirement in requirements[1:]:
            existing = await db.scalar(
                select(CaseRecord).where(CaseRecord.requirement_id == requirement.id)
            )
            if existing and await context.repository.ticket_by_case(db, existing.id):
                continue
            requirement.confirmation_decision = True
            case = existing or await confirmation_nodes.create_case_for_requirement(
                db, kiosk_session, requirement
            )
            if requirement.consultation_level != ConsultationLevel.GENERAL:
                if identifier_payload is None:
                    raise AppError(
                        "BATCH_IDENTIFICATION_REQUIRED",
                        "La identificación del conjunto todavía está pendiente",
                        409,
                    )
                resolved = await resolve_identifier(db, identifier_payload, context.settings)
                await record_identification(
                    db,
                    case,
                    identifier_payload,
                    resolved,
                    context.settings,
                )
            await finalize_subgraph.ainvoke(
                {"kiosk_session": kiosk_session, "requirement": requirement, "case": case},
                context=context,
            )

        await self._restore_primary_projection(db, kiosk_session, primary)

    @staticmethod
    async def _restore_primary_projection(
        db: AsyncSession,
        kiosk_session: KioskSession,
        primary: Requirement,
    ) -> None:
        primary_case = await db.scalar(
            select(CaseRecord).where(CaseRecord.requirement_id == primary.id)
        )
        cases = list(
            await db.scalars(
                select(CaseRecord)
                .join(Requirement, CaseRecord.requirement_id == Requirement.id)
                .where(
                    CaseRecord.session_id == kiosk_session.id,
                    Requirement.turn_id == primary.turn_id,
                )
            )
        )
        kiosk_session.status = (
            SessionStatus.ASSIGNED
            if any(case.resolution_type is ResolutionType.HUMAN for case in cases)
            else SessionStatus.RESOLVED_AUTOMATIC
        )
        if primary_case:
            kiosk_session.resolution_type = primary_case.resolution_type
            kiosk_session.final_response = primary_case.final_response
            kiosk_session.grounding_status = primary_case.grounding_status
            kiosk_session.citations_json = primary_case.citations_json
            kiosk_session.grounding_detail_json = primary_case.grounding_detail_json
