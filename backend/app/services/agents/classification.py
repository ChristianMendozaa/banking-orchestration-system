"""The classification agent.

One structured model call, then three deterministic layers that second-guess it:
`_ensure_customer_language` (rewrites unnatural customer-facing wording),
`_enforce_sensitivity` (raises the consultation level to the floor, never lowers it),
and `_fallback` (a pure keyword classifier for when the provider is down).

The prompt this sends lives in `app.services.prompts.classification`.
"""

import structlog

from app.core.config import Settings
from app.domain.enums import Category, ClarificationOutcome, ConsultationLevel
from app.domain.schemas import ClassificationDecision, ClassifiedNeed
from app.services.agents.rules.categories import category_from_keywords
from app.services.agents.rules.language import (
    _NATURAL_SUMMARY_OPENING,
    _SUMMARY_IS_A_QUESTION,
    customer_facing_text_is_natural,
    customer_summary_for,
    summary_lists_an_unreturned_need,
)
from app.services.agents.rules.sensitivity import (
    _LEVEL_ORDER,
    incident_floor,
    possession_floor,
    security_incident_category,
    sensitivity_floor,
)
from app.services.anthropic_provider import AnthropicProvider
from app.services.intake import IntakePlanner
from app.services.prompts import CLASSIFICATION_NEEDS_FEEDBACK

logger = structlog.get_logger()

# `Requirement.classification_source` when the possession floor was read against the
# clarification alone and that changed what it would have enforced: the requirement, and the
# trace event of any case opened from it, record that the opener's signal was not applied.
SCOPED_FLOOR_SOURCE = "MODEL+SCOPED"


class ClassificationAgent:
    def __init__(
        self,
        settings: Settings,
        provider: AnthropicProvider | None,
        intake_planner: IntakePlanner | None = None,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.intake_planner = intake_planner or IntakePlanner()

    async def run(self, masked_text: str) -> ClassificationDecision:
        decision, _ = await self.run_with_source(masked_text)
        return decision

    async def run_with_source(
        self,
        masked_text: str,
        classification_input: str | None = None,
        latest_reply: str | None = None,
    ) -> tuple[ClassificationDecision, str]:
        """`latest_reply` is set only on a clarification turn: what the person said when the
        kiosk asked, as opposed to the accumulated `masked_text` it was appended to."""
        if self.provider:
            try:
                decision = await self._classify_consistently(classification_input or masked_text)
                decision = self._ensure_customer_language(decision)
                decision, source = self._enforce_sensitivity(decision, masked_text, latest_reply)
                decision = self._recover_omitted_security_need(decision, masked_text)
                return self.intake_planner.plan(decision), source
            except Exception as exc:
                logger.warning(
                    "classification_provider_fallback",
                    error_type=type(exc).__name__,
                )
        # `_fallback` derives the level from the same keyword tables the floor uses, so
        # running the floor over it again would be a no-op.
        return self._fallback(masked_text), "FALLBACK"

    async def _classify_consistently(self, payload: str) -> ClassificationDecision:
        """One model decision, retried once when it contradicts itself.

        A customer_summary that reads back a second need ("...y también saber a qué hora
        abre") with no additional_needs gets confirmed by the person and then delivers only
        the first need: `multi_intencion` lost the hours question this way in one of three
        repetitions on 2026-10-21, on the exact sentence the other two split correctly. The
        retry says what was wrong and lets the model decide again; the text is never split
        here, because "bloquear tu tarjeta y también que te devuelvan el dinero" is one
        incident, and a second answer that still disagrees with itself is kept as it is.
        """
        decision = await self.provider.classify(payload)
        if not summary_lists_an_unreturned_need(
            decision.customer_summary, len(decision.additional_needs)
        ):
            return decision
        logger.info("classification_needs_retried", category=decision.category.value)
        try:
            return await self.provider.classify(payload, feedback=CLASSIFICATION_NEEDS_FEEDBACK)
        except Exception as exc:
            logger.warning("classification_needs_retry_failed", error_type=type(exc).__name__)
            return decision

    @staticmethod
    def _enforce_sensitivity(
        decision: ClassificationDecision, masked_text: str, latest_reply: str | None = None
    ) -> tuple[ClassificationDecision, str]:
        """Raises the model's consultation level to the deterministic floor when the text
        says the request is about this person's own money, plastic or access. Never lowers
        it -- the model is better than any keyword list at the calls this doesn't cover, and
        an over-classification only costs one confirmation turn, while an
        under-classification costs identification and human escalation outright.

        On a clarification that supplied the detail (PROVIDED_DETAIL), the possession half
        of the floor reads only what the person said when asked, plus the classifier's
        context-resolved restatement of it. The opener is by definition the part the kiosk
        could not understand, and an aside in it -- "tenía que hacer un trámite de mi
        cuenta, pero eso después le cuento" -- turned a branch-hours question into
        identification and a ticket (`horarios_ambiguo`, 2026-10-21). The restatement keeps
        a personal topic personal: "el saldo", said after "algo de mi cuenta", comes back
        as "el saldo de mi cuenta". The incident half always reads the whole conversation:
        a theft mentioned in the opener is never scoped away."""
        category = decision.category
        floor = sensitivity_floor(masked_text, category)
        scoped = (
            latest_reply is not None
            and decision.clarification_outcome is ClarificationOutcome.PROVIDED_DETAIL
        )
        if scoped:
            current = f"{latest_reply}\n{decision.standalone_question or ''}"
            scoped_floor = incident_floor(masked_text, category) or possession_floor(
                current, category
            )
            if scoped_floor != floor:
                logger.info(
                    "classification_floor_scoped",
                    category=category.value,
                    accumulated_floor=floor.value if floor else None,
                    scoped_floor=scoped_floor.value if scoped_floor else None,
                )
                floor = scoped_floor
            else:
                scoped = False
        if floor is None or _LEVEL_ORDER[floor] <= _LEVEL_ORDER[decision.consultation_level]:
            return decision, SCOPED_FLOOR_SOURCE if scoped else "MODEL"
        logger.warning(
            "classification_level_raised",
            category=category.value,
            model_level=decision.consultation_level.value,
            enforced_level=floor.value,
        )
        return decision.model_copy(update={"consultation_level": floor}), "MODEL+FLOOR"

    @staticmethod
    def _ensure_customer_language(decision: ClassificationDecision) -> ClassificationDecision:
        customer_summary = decision.customer_summary.strip()
        if not customer_facing_text_is_natural(customer_summary) or not (
            _NATURAL_SUMMARY_OPENING.search(customer_summary)
        ):
            customer_summary = customer_summary_for(decision.category)

        # A summary that hands the question back ("Necesitas decirme si quieres bloquear tu
        # tarjeta o reportar un fraude") is a clarification wearing a requirement's clothes.
        # It passes the opening check above, and confirming it produces the loop seen in the
        # `cliente_no_entiende_la_pregunta` eval: CONFIRM -> rejected -> CAPTURE -> CONFIRM.
        # Treat it as what it is, so `turn_nodes.route_ambiguity` puts the turn back on the
        # clarify -> force_human ladder instead.
        ambiguous = decision.ambiguous or bool(_SUMMARY_IS_A_QUESTION.search(customer_summary))

        clarification_question = decision.clarification_question
        if ambiguous and (
            not clarification_question
            or not customer_facing_text_is_natural(clarification_question)
        ):
            clarification_question = (
                "¿Me cuentas brevemente qué trámite o problema necesitas resolver?"
            )
        return decision.model_copy(
            update={
                "customer_summary": customer_summary,
                "clarification_question": clarification_question,
                "ambiguous": ambiguous,
            }
        )

    @staticmethod
    def _recover_omitted_security_need(
        decision: ClassificationDecision, masked_text: str
    ) -> ClassificationDecision:
        category = security_incident_category(masked_text)
        existing_categories = {
            decision.category,
            *(need.category for need in decision.additional_needs),
        }
        if category is None or category in existing_categories:
            return decision
        if category is Category.REPORTE_FRAUDE:
            summary = "Reporta un posible cobro o movimiento no reconocido"
            customer = "Necesitas reportar un posible cobro o movimiento no reconocido."
        else:
            summary = "Reporta la pérdida o robo de una tarjeta"
            customer = "Necesitas reportar la pérdida o robo de una tarjeta."
        combined = decision.customer_summary.rstrip(". ")
        if combined.lower().startswith("necesitas "):
            combined = combined[len("Necesitas ") :]
        return decision.model_copy(
            update={
                "customer_summary": f"{customer.rstrip('.')} y también {combined}.",
                "additional_needs": [
                    *decision.additional_needs,
                    ClassifiedNeed(
                        summary=summary,
                        customer_summary=customer,
                        category=category,
                        consultation_level=ConsultationLevel.SENSIBLE,
                        confidence=1.0,
                        urgency_detected=True,
                        security_incident=True,
                    ),
                ],
            }
        )

    @staticmethod
    def _fallback(text: str) -> ClassificationDecision:
        lowered = text.lower()
        category = category_from_keywords(text)
        if category:
            sensitive = category in {Category.REPORTE_FRAUDE, Category.BLOQUEO_TARJETA} or any(
                term in lowered
                for term in ("saldo", "mis movimientos", "datos financieros", "mi tarjeta")
            )
            informational = any(
                term in lowered
                for term in (
                    "informacion",
                    "información",
                    "requisito",
                    "que necesito",
                    "qué necesito",
                    "horario",
                    "donde",
                    "dónde",
                    "como funciona",
                    "cómo funciona",
                )
            )
            personalized = any(
                term in lowered
                for term in (
                    "mi credito",
                    "mi crédito",
                    "mi solicitud",
                    "estado de",
                    "no puedo acceder",
                    "contraseña bloqueada",
                    "mi cuenta",
                )
            )
            heuristic_level = (
                ConsultationLevel.SENSIBLE
                if sensitive
                else ConsultationLevel.PERSONALIZADA
                if personalized and not informational
                else ConsultationLevel.GENERAL
            )
            floor = sensitivity_floor(text, category)
            level = (
                floor
                if floor is not None and _LEVEL_ORDER[floor] > _LEVEL_ORDER[heuristic_level]
                else heuristic_level
            )
            return ClassificationDecision(
                summary=text[:500],
                customer_summary=customer_summary_for(category),
                category=category,
                consultation_level=level,
                confidence=0.86,
                ambiguous=False,
                urgency_detected=category in {Category.REPORTE_FRAUDE, Category.BLOQUEO_TARJETA},
                security_incident=category in {Category.REPORTE_FRAUDE, Category.BLOQUEO_TARJETA},
            )
        return ClassificationDecision(
            summary=text[:500],
            customer_summary=customer_summary_for(Category.CONSULTA_GENERAL),
            category=Category.CONSULTA_GENERAL,
            consultation_level=ConsultationLevel.GENERAL,
            confidence=0.42,
            ambiguous=True,
            clarification_question=(
                "¿Me cuentas brevemente qué trámite o problema necesitas resolver?"
            ),
        )
