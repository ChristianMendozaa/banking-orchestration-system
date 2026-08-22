"""The classification agent.

One structured model call, then three deterministic layers that second-guess it:
`_ensure_customer_language` (rewrites unnatural customer-facing wording),
`_enforce_sensitivity` (raises the consultation level to the floor, never lowers it),
and `_fallback` (a pure keyword classifier for when the provider is down).

The prompt this sends lives in `app.services.prompts.classification`.
"""

import structlog

from app.core.config import Settings
from app.domain.enums import Category, ConsultationLevel
from app.domain.schemas import ClassificationDecision
from app.services.agents.rules.categories import category_from_keywords
from app.services.agents.rules.language import (
    _NATURAL_SUMMARY_OPENING,
    _SUMMARY_IS_A_QUESTION,
    customer_facing_text_is_natural,
    customer_summary_for,
)
from app.services.agents.rules.sensitivity import _LEVEL_ORDER, sensitivity_floor
from app.services.openai_provider import OpenAIProvider

logger = structlog.get_logger()


class ClassificationAgent:
    def __init__(self, settings: Settings, provider: OpenAIProvider | None) -> None:
        self.settings = settings
        self.provider = provider

    async def run(self, masked_text: str) -> ClassificationDecision:
        decision, _ = await self.run_with_source(masked_text)
        return decision

    async def run_with_source(self, masked_text: str) -> tuple[ClassificationDecision, str]:
        if self.provider:
            try:
                decision = self._ensure_customer_language(await self.provider.classify(masked_text))
                return self._enforce_sensitivity(decision, masked_text)
            except Exception as exc:
                logger.warning(
                    "classification_provider_fallback",
                    error_type=type(exc).__name__,
                )
        # `_fallback` derives the level from the same keyword tables the floor uses, so
        # running the floor over it again would be a no-op.
        return self._fallback(masked_text), "FALLBACK"

    @staticmethod
    def _enforce_sensitivity(
        decision: ClassificationDecision, masked_text: str
    ) -> tuple[ClassificationDecision, str]:
        """Raises the model's consultation level to the deterministic floor when the text
        says the request is about this person's own money, plastic or access. Never lowers
        it -- the model is better than any keyword list at the calls this doesn't cover, and
        an over-classification only costs one confirmation turn, while an
        under-classification costs identification and human escalation outright."""
        floor = sensitivity_floor(masked_text, decision.category)
        if floor is None or _LEVEL_ORDER[floor] <= _LEVEL_ORDER[decision.consultation_level]:
            return decision, "MODEL"
        logger.warning(
            "classification_level_raised",
            category=decision.category.value,
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
            if sensitive:
                level = ConsultationLevel.SENSIBLE
            elif personalized and not informational:
                level = ConsultationLevel.PERSONALIZADA
            else:
                level = ConsultationLevel.GENERAL
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
