import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Executive
from app.db.repositories import ExecutiveRepository
from app.domain.enums import (
    Category,
    ConsultationLevel,
    Priority,
)
from app.domain.schemas import ClassificationDecision, GroundedResponse
from app.knowledge.service import KnowledgeService
from app.services.openai_provider import OpenAIProvider

logger = structlog.get_logger()

_CUSTOMER_SUMMARIES = {
    Category.BLOQUEO_TARJETA: "Necesitas bloquear una tarjeta.",
    Category.REPORTE_FRAUDE: (
        "Necesitas reportar un posible fraude o un movimiento no reconocido."
    ),
    Category.CONSULTA_GENERAL: "Necesitas orientación sobre una consulta bancaria.",
    Category.SOLICITUD_CREDITO: ("Quieres información o ayuda con una solicitud de crédito."),
    Category.BANCA_DIGITAL: "Necesitas ayuda con la banca digital.",
}
_UNNATURAL_CUSTOMER_LANGUAGE = re.compile(
    r"\busuario\b|\b(?:el|la|un|una)\s+(?:cliente|persona)\b|"
    r"\b(?:usted|su|sus)\b|"
    r"\b(?:puede|podría|podria|indique|ingrese|describa|dígame|digame|"
    r"confirme|cuénteme|cuenteme|responda|escriba|necesita)\b",
    re.IGNORECASE,
)
_NATURAL_SUMMARY_OPENING = re.compile(
    r"^(?:necesitas|quieres|buscas|deseas|solicitas|reportas|tienes|te\b|"
    r"no\s+reconoces|notaste|identificaste)",
    re.IGNORECASE,
)
# Narrower than _UNNATURAL_CUSTOMER_LANGUAGE: a multi-sentence RAG answer legitimately uses
# "puede", "necesita" or "su" to talk about the bank or the product ("el banco puede pedir tu
# documento"), so only third-person references to the person asking, and usted-form address,
# disqualify it.
_UNNATURAL_THIRD_PERSON_REFERENCE = re.compile(
    r"\busuario\b|\b(?:el|la|un|una)\s+(?:cliente|persona)\b|\b(?:usted|ustedes)\b",
    re.IGNORECASE,
)


def customer_summary_for(category: Category) -> str:
    return _CUSTOMER_SUMMARIES[category]


def customer_facing_text_is_natural(text: str) -> bool:
    return not _UNNATURAL_CUSTOMER_LANGUAGE.search(text)


def grounded_answer_is_natural(text: str) -> bool:
    return not _UNNATURAL_THIRD_PERSON_REFERENCE.search(text)


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
                return (
                    self._ensure_customer_language(await self.provider.classify(masked_text)),
                    "MODEL",
                )
            except Exception as exc:
                logger.warning(
                    "classification_provider_fallback",
                    error_type=type(exc).__name__,
                )
        return self._fallback(masked_text), "FALLBACK"

    @staticmethod
    def _ensure_customer_language(decision: ClassificationDecision) -> ClassificationDecision:
        customer_summary = decision.customer_summary.strip()
        if not customer_facing_text_is_natural(customer_summary) or not (
            _NATURAL_SUMMARY_OPENING.search(customer_summary)
        ):
            customer_summary = customer_summary_for(decision.category)

        clarification_question = decision.clarification_question
        if decision.ambiguous and (
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
            }
        )

    @staticmethod
    def _fallback(text: str) -> ClassificationDecision:
        lowered = text.lower()
        category_rules = (
            (
                Category.REPORTE_FRAUDE,
                (
                    "fraude",
                    "movimiento no reconocido",
                    "compra no reconocida",
                    "no reconozco",
                    "estafa",
                ),
            ),
            (
                Category.BLOQUEO_TARJETA,
                ("bloquear", "bloqueo", "tarjeta perdida", "tarjeta robada", "extrav"),
            ),
            (
                Category.BANCA_DIGITAL,
                ("banca digital", "banca en linea", "aplicacion", "contraseña", "acceso"),
            ),
            (
                Category.SOLICITUD_CREDITO,
                ("credito", "crédito", "prestamo", "préstamo", "hipotecario"),
            ),
            (
                Category.CONSULTA_GENERAL,
                ("horario", "requisito", "abrir una cuenta", "sucursal", "producto"),
            ),
        )
        category = next(
            (
                candidate
                for candidate, keywords in category_rules
                if any(keyword in lowered for keyword in keywords)
            ),
            None,
        )
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


class PrioritizationAgent:
    _order = [Priority.BAJO, Priority.MEDIO, Priority.ALTO, Priority.CRITICO]

    def run(
        self,
        category: Category,
        summary: str,
        preferential: bool,
        urgency_detected: bool = False,
        security_incident: bool = False,
        distress_detected: bool = False,
    ) -> Priority:
        lowered = summary.lower()
        if category == Category.REPORTE_FRAUDE or "movimiento no reconocido" in lowered:
            priority = Priority.CRITICO
        elif category == Category.BLOQUEO_TARJETA or (security_incident and urgency_detected):
            priority = Priority.ALTO
        elif category in {Category.SOLICITUD_CREDITO, Category.BANCA_DIGITAL} or urgency_detected:
            priority = Priority.MEDIO
        else:
            priority = Priority.BAJO
        if distress_detected and priority in {Priority.BAJO, Priority.MEDIO}:
            priority = self._order[self._order.index(priority) + 1]
        if preferential and priority not in {Priority.ALTO, Priority.CRITICO}:
            priority = self._order[self._order.index(priority) + 1]
        return priority


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return numerator / denominator if denominator else 0.0


@dataclass(frozen=True, slots=True)
class DerivationDecision:
    executive: Executive
    score: float
    semantic_score: float
    experience_score: float
    load_score: float
    active_load: int


class DerivationAgent:
    def __init__(
        self,
        provider: OpenAIProvider | None,
        repository: ExecutiveRepository | None = None,
    ) -> None:
        self.provider = provider
        self.repository = repository or ExecutiveRepository()

    async def run(
        self, db: AsyncSession, category: Category, summary: str
    ) -> DerivationDecision | None:
        ranked = await self._rank(db, category, summary)
        return ranked[0][3] if ranked else None

    async def explain(
        self, db: AsyncSession, category: Category, summary: str
    ) -> list[DerivationDecision]:
        """Return every candidate's scoring breakdown, best first.

        Read-only replay of `run()`'s ranking for the `explain_routing_decision` MCP
        tool. Does not affect routing: `run()` still owns the actual assignment.
        """
        ranked = await self._rank(db, category, summary)
        return [row[3] for row in ranked]

    async def _rank(
        self, db: AsyncSession, category: Category, summary: str
    ) -> list[tuple[float, datetime, str, DerivationDecision]]:
        executives = await self.repository.available(db)
        if not executives:
            return []

        loads = await self.repository.active_loads(db)
        max_load = max([*loads.values(), 1])

        case_embedding: list[float] | None = None
        if self.provider:
            try:
                case_embedding = await self.provider.embedding(summary)
            except Exception as exc:
                logger.warning(
                    "routing_embedding_fallback",
                    error_type=type(exc).__name__,
                )
                case_embedding = None

        ranked: list[tuple[float, datetime, str, DerivationDecision]] = []
        for executive in executives:
            matching = [skill for skill in executive.skills if skill.category == category]
            if not matching:
                continue
            best_skill = max(matching, key=lambda skill: skill.experience_level)
            semantic = 1.0 if case_embedding is None else 0.0
            if case_embedding is not None:
                try:
                    if best_skill.embedding is None and self.provider:
                        best_skill.embedding = await self.provider.embedding(best_skill.description)
                    if best_skill.embedding is not None:
                        semantic = max(
                            0.0,
                            _cosine(case_embedding, list(best_skill.embedding)),
                        )
                except Exception as exc:
                    logger.warning(
                        "routing_skill_embedding_fallback",
                        executive_id=str(executive.id),
                        error_type=type(exc).__name__,
                    )
            experience = min(max(best_skill.experience_level, 1), 5) / 5
            load_score = 1 - (loads[executive.id] / max_load)
            score = 0.70 * semantic + 0.20 * experience + 0.10 * load_score
            idle = executive.last_assigned_at or datetime.min.replace(tzinfo=UTC)
            ranked.append(
                (
                    score,
                    idle,
                    str(executive.id),
                    DerivationDecision(
                        executive=executive,
                        score=score,
                        semantic_score=semantic,
                        experience_score=experience,
                        load_score=load_score,
                        active_load=loads[executive.id],
                    ),
                )
            )
        ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
        return ranked


class InitialAttentionAgent:
    def __init__(self, knowledge: KnowledgeService) -> None:
        self.knowledge = knowledge

    async def run(
        self,
        db: AsyncSession,
        case_id: UUID,
        category: Category,
        level: ConsultationLevel,
        masked_query: str,
    ) -> GroundedResponse | None:
        if level != ConsultationLevel.GENERAL:
            return None
        response = await self.knowledge.answer(db, case_id, category, masked_query)
        if response and not grounded_answer_is_natural(response.answer):
            logger.warning("grounded_answer_rejected", case_id=str(case_id), category=category)
            return None
        return response
