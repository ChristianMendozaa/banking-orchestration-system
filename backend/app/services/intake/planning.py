"""Convert classified candidate needs into independent operational case needs.

The classifier is intentionally generous: it should retain every material concern it hears.
That does not mean every concern owns a queue ticket. This module is the deterministic policy
boundary between language understanding and case creation.
"""

from enum import StrEnum

from app.domain.enums import Category, ConsultationLevel
from app.domain.schemas import ClassificationDecision, ClassifiedNeed
from app.services.agents.rules.sensitivity import _LEVEL_ORDER, sensitivity_floor


class WorkflowFamily(StrEnum):
    SECURITY_INCIDENT = "SECURITY_INCIDENT"
    GENERAL_SERVICE = "GENERAL_SERVICE"
    CREDIT = "CREDIT"
    DIGITAL_BANKING = "DIGITAL_BANKING"


_WORKFLOW_FAMILY = {
    Category.REPORTE_FRAUDE: WorkflowFamily.SECURITY_INCIDENT,
    Category.BLOQUEO_TARJETA: WorkflowFamily.SECURITY_INCIDENT,
    Category.CONSULTA_GENERAL: WorkflowFamily.GENERAL_SERVICE,
    Category.SOLICITUD_CREDITO: WorkflowFamily.CREDIT,
    Category.BANCA_DIGITAL: WorkflowFamily.DIGITAL_BANKING,
}

_CATEGORY_RANK = {
    Category.CONSULTA_GENERAL: 0,
    Category.SOLICITUD_CREDITO: 1,
    Category.BANCA_DIGITAL: 2,
    Category.BLOQUEO_TARJETA: 3,
    Category.REPORTE_FRAUDE: 4,
}

_SUMMARY_LIMIT = 500


def _merge_case_details(values: list[str]) -> str:
    """Keep every consolidated action visible within the schema's summary limit.

    A plain prefix truncation can erase the later action entirely. Dividing the available
    space across the distinct details retains an operationally useful description of each
    action even when model-produced summaries are unusually long.
    """
    distinct = list(dict.fromkeys(" ".join(value.split()).strip(" .;") for value in values))
    if len(distinct) == 1:
        return distinct[0]

    separator = "; "
    share = (_SUMMARY_LIMIT - len(separator) * (len(distinct) - 1)) // len(distinct)
    parts: list[str] = []
    for value in distinct:
        if len(value) <= share:
            parts.append(value)
            continue
        shortened = value[:share].rsplit(" ", 1)[0].rstrip(" .;")
        parts.append(shortened or value[:share])
    return separator.join(parts)


class IntakePlanner:
    """Return one candidate per independent case, ordered by operational risk.

    Fraud reporting and protective card blocking raised in the same turn belong to one
    security-incident workflow: the security specialist owns both actions and the customer
    must receive one destination. Other combinations remain independent because they may be
    answered or routed separately.
    """

    def plan(self, decision: ClassificationDecision) -> ClassificationDecision:
        primary = ClassifiedNeed(
            summary=decision.summary,
            customer_summary=decision.customer_summary,
            category=decision.category,
            consultation_level=decision.consultation_level,
            confidence=decision.confidence,
            urgency_detected=decision.urgency_detected,
            security_incident=decision.security_incident,
            distress_detected=decision.distress_detected,
        )
        candidates = [
            self._apply_sensitivity_floor(primary),
            *map(self._apply_sensitivity_floor, decision.additional_needs),
        ]
        candidates = self._deduplicate_exact_candidates(candidates)
        candidates = self._consolidate_security_incident(candidates)
        candidates.sort(key=self._risk_key, reverse=True)

        first, *additional = candidates
        return decision.model_copy(
            update={
                "summary": first.summary,
                # The model's primary customer summary covers the whole confirmed intake.
                # It remains useful after ordering or consolidation, while each additional
                # candidate keeps its own single-need summary.
                "customer_summary": decision.customer_summary,
                "category": first.category,
                "consultation_level": first.consultation_level,
                "confidence": first.confidence,
                "urgency_detected": first.urgency_detected,
                "security_incident": first.security_incident,
                "distress_detected": first.distress_detected,
                "additional_needs": additional,
            }
        )

    @staticmethod
    def _apply_sensitivity_floor(need: ClassifiedNeed) -> ClassifiedNeed:
        floor = sensitivity_floor(need.summary, need.category)
        if floor is None or _LEVEL_ORDER[floor] <= _LEVEL_ORDER[need.consultation_level]:
            return need
        return need.model_copy(update={"consultation_level": floor})

    @staticmethod
    def _deduplicate_exact_candidates(needs: list[ClassifiedNeed]) -> list[ClassifiedNeed]:
        unique: list[ClassifiedNeed] = []
        seen: set[tuple[Category, str]] = set()
        for need in needs:
            normalized = " ".join(need.summary.casefold().split()).strip(" .")
            key = (need.category, normalized)
            if key not in seen:
                seen.add(key)
                unique.append(need)
        return unique

    @staticmethod
    def _consolidate_security_incident(needs: list[ClassifiedNeed]) -> list[ClassifiedNeed]:
        security = [
            need
            for need in needs
            if _WORKFLOW_FAMILY[need.category] is WorkflowFamily.SECURITY_INCIDENT
        ]
        if len(security) < 2:
            return needs

        owner = max(security, key=lambda need: _CATEGORY_RANK[need.category])
        owner = owner.model_copy(
            update={
                # One customer destination must not mean one lost action. The case and
                # ticket retain the detail of every concern absorbed by this workflow.
                "summary": _merge_case_details([need.summary for need in security]),
                "customer_summary": _merge_case_details(
                    [need.customer_summary for need in security]
                ),
                "consultation_level": ConsultationLevel.SENSIBLE,
                "confidence": max(need.confidence for need in security),
                "urgency_detected": any(need.urgency_detected for need in security),
                "security_incident": any(need.security_incident for need in security),
                "distress_detected": any(need.distress_detected for need in security),
            }
        )
        first_security_index = min(needs.index(need) for need in security)
        independent = [need for need in needs if need not in security]
        independent.insert(min(first_security_index, len(independent)), owner)
        return independent

    @staticmethod
    def _risk_key(need: ClassifiedNeed) -> tuple[bool, int, int]:
        level_rank = {
            ConsultationLevel.GENERAL: 0,
            ConsultationLevel.PERSONALIZADA: 1,
            ConsultationLevel.SENSIBLE: 2,
        }
        return (
            need.security_incident,
            level_rank[need.consultation_level],
            _CATEGORY_RANK[need.category],
        )
