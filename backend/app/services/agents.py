import math
from datetime import UTC, datetime
from uuid import UUID

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


class ClassificationAgent:
    def __init__(self, settings: Settings, provider: OpenAIProvider | None) -> None:
        self.settings = settings
        self.provider = provider

    async def run(self, masked_text: str) -> ClassificationDecision:
        if self.provider:
            try:
                return await self.provider.classify(masked_text)
            except Exception:
                pass
        return self._fallback(masked_text)

    @staticmethod
    def _fallback(text: str) -> ClassificationDecision:
        lowered = text.lower()
        rules = (
            (
                Category.REPORTE_FRAUDE,
                ConsultationLevel.SENSIBLE,
                ("fraude", "movimiento no reconocido", "compra no reconocida", "estafa"),
            ),
            (
                Category.BLOQUEO_TARJETA,
                ConsultationLevel.SENSIBLE,
                ("bloquear", "bloqueo", "tarjeta perdida", "tarjeta robada", "extrav"),
            ),
            (
                Category.BANCA_DIGITAL,
                ConsultationLevel.PERSONALIZADA,
                ("banca digital", "banca en linea", "aplicacion", "contraseña", "acceso"),
            ),
            (
                Category.SOLICITUD_CREDITO,
                ConsultationLevel.PERSONALIZADA,
                ("credito", "crédito", "prestamo", "préstamo", "hipotecario"),
            ),
            (
                Category.CONSULTA_GENERAL,
                ConsultationLevel.GENERAL,
                ("horario", "requisito", "abrir una cuenta", "sucursal", "producto"),
            ),
        )
        for category, level, keywords in rules:
            if any(keyword in lowered for keyword in keywords):
                return ClassificationDecision(
                    summary=text[:500],
                    category=category,
                    consultation_level=level,
                    confidence=0.86,
                    ambiguous=False,
                    urgency_detected=category
                    in {Category.REPORTE_FRAUDE, Category.BLOQUEO_TARJETA},
                    security_incident=category
                    in {Category.REPORTE_FRAUDE, Category.BLOQUEO_TARJETA},
                )
        return ClassificationDecision(
            summary=text[:500],
            category=Category.CONSULTA_GENERAL,
            consultation_level=ConsultationLevel.GENERAL,
            confidence=0.42,
            ambiguous=True,
            clarification_question=(
                "¿Podria indicar brevemente que tramite o problema necesita resolver?"
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
        if (
            category == Category.REPORTE_FRAUDE
            or "movimiento no reconocido" in lowered
            or security_incident
            and urgency_detected
        ):
            priority = Priority.CRITICO
        elif (
            category == Category.BLOQUEO_TARJETA
            or urgency_detected
            or any(term in lowered for term in ("urgente", "seguridad", "robada", "bloquear"))
        ):
            priority = Priority.ALTO
        elif category in {Category.SOLICITUD_CREDITO, Category.BANCA_DIGITAL}:
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


class DerivationAgent:
    def __init__(
        self,
        provider: OpenAIProvider | None,
        repository: ExecutiveRepository | None = None,
    ) -> None:
        self.provider = provider
        self.repository = repository or ExecutiveRepository()

    async def run(self, db: AsyncSession, category: Category, summary: str) -> Executive | None:
        executives = await self.repository.available(db)
        if not executives:
            return None

        loads = await self.repository.active_loads(db)
        max_load = max([*loads.values(), 1])

        case_embedding: list[float] | None = None
        if self.provider:
            try:
                case_embedding = await self.provider.embedding(summary)
            except Exception:
                case_embedding = None

        ranked: list[tuple[float, datetime, str, Executive]] = []
        for executive in executives:
            matching = [skill for skill in executive.skills if skill.category == category]
            best_skill = max(matching or executive.skills, key=lambda skill: skill.experience_level)
            semantic = 1.0 if best_skill.category == category else 0.25
            if case_embedding is not None:
                try:
                    if best_skill.embedding is None and self.provider:
                        best_skill.embedding = await self.provider.embedding(best_skill.description)
                    if best_skill.embedding is not None:
                        semantic = max(
                            semantic, _cosine(case_embedding, list(best_skill.embedding))
                        )
                except Exception:
                    pass
            experience = min(max(best_skill.experience_level, 1), 5) / 5
            load_score = 1 - (loads[executive.id] / max_load)
            score = 0.70 * semantic + 0.20 * experience + 0.10 * load_score
            idle = executive.last_assigned_at or datetime.min.replace(tzinfo=UTC)
            ranked.append((score, idle, str(executive.id), executive))
        ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
        return ranked[0][3]


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
        if category != Category.CONSULTA_GENERAL or level != ConsultationLevel.GENERAL:
            return None
        return await self.knowledge.answer(db, case_id, category, masked_query)
