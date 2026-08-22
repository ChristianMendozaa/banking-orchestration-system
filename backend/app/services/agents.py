import math
import re
from collections.abc import Sequence
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
# A customer_summary that restates the clarification instead of the need: `decirme`,
# `contarme`, `indicarme` and `falta saber` all mark the kiosk still asking rather than
# summarising something it understood.
_SUMMARY_IS_A_QUESTION = re.compile(
    r"\b(?:decirme|contarme|indicarme|precisarme|aclararme|falta\s+saber|"
    r"especificar(?:me)?)\b",
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


# Category keyword rules, shared by `ClassificationAgent._fallback` (which needs them to
# classify at all when the provider is down) and by `sensitivity_floor` below (which needs
# them to second-guess a provider that answered). Keeping one copy is the point: a floor that
# drifts from the fallback is a floor nobody can reason about.
_CATEGORY_RULES: tuple[tuple[Category, tuple[str, ...]], ...] = (
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

_LEVEL_ORDER = {
    ConsultationLevel.GENERAL: 0,
    ConsultationLevel.PERSONALIZADA: 1,
    ConsultationLevel.SENSIBLE: 2,
}

# Something already happened to this person's own money or plastic. These phrasings are not
# ambiguous in Bolivian Spanish and they survive the hypothetical guard below: "me robaron"
# is never preventive.
_INCIDENT_EVENT = re.compile(
    r"me\s+robaron|robaron\s+mi|me\s+clonaron|clonaron\s+(?:mi|la)|me\s+sacaron|"
    r"no\s+reconozco|no\s+reconoc[ií]|no\s+autoric[eé]|"
    r"me\s+(?:aparec|sali)\w*\s+(?:un|dos|tres|varios)?\s*"
    r"(?:cargo|cobro|consumo|movimiento|consumos|cargos)|"
    r"se\s+trag[oó]\s+mi\s+tarjeta|me\s+(?:la|lo)\s+(?:usaron|vaciaron)|"
    r"perd[ií]\s+mi\b|se\s+me\s+perdi[oó]|extravi[eé]",
    re.IGNORECASE,
)
# Weaker than _INCIDENT_EVENT: naming one's own banking object is enough to make a request
# personal, but a preventive question can mention the same objects, so the hypothetical guard
# can veto these.
_OWN_BANKING_OBJECT = re.compile(
    r"\bmi\s+tarjeta\b|\bmis?\s+cuentas?\b|\bmis\s+movimientos\b|\bmi\s+saldo\b|"
    r"\bmi\s+plata\b|\bmi\s+dinero\b",
    re.IGNORECASE,
)
# Own file / own access, with no incident and no money moving: PERSONALIZADA territory.
_OWN_FILE_OR_ACCESS = re.compile(
    r"no\s+puedo\s+(?:acceder|entrar|ingresar)|no\s+logro\s+(?:entrar|ingresar|acceder)|"
    r"\bmi\s+(?:contraseña|contrasena|clave|usuario|app|aplicaci[oó]n|extracto|"
    r"solicitud|cr[eé]dito|pr[eé]stamo|tr[aá]mite)\b|"
    r"estado\s+de\s+mi\b|c[oó]mo\s+va\s+mi\b",
    re.IGNORECASE,
)
# A digital-banking request that reports an operation of one's own failing. Named separately
# because these phrasings carry no possessive at all ("hice tres intentos de transferencia y
# las tres veces fallo") and would otherwise read as a product question.
_DIGITAL_OPERATION_FAILURE = re.compile(
    r"fall[oó]|fallaron|no\s+me\s+deja|no\s+funciona|me\s+rechaz|rechazad|"
    r"\bintentos?\b|\berror\b|bloquead",
    re.IGNORECASE,
)
# Preventive or hypothetical framing. Vetoes _OWN_BANKING_OBJECT and the digital-failure rule,
# never _INCIDENT_EVENT.
_HYPOTHETICAL = re.compile(
    r"si\s+alg[uú]n\s+d[ií]a|por\s+si\s+acaso|por\s+si\s+alguna\s+vez|por\s+prevenci[oó]n|"
    r"en\s+caso\s+de\s+que|no\s+me\s+pas[oó]\s+nada|todav[ií]a\s+no|hipot[eé]tic|"
    r"a[uú]n\s+no\s+soy\s+cliente|no\s+es\s+(?:un\s+)?caso\s+real",
    re.IGNORECASE,
)


# A negator immediately before an incident phrase reverses it: "no me robaron nada" and "ni me
# robaron" are someone stating that nothing happened, and `_INCIDENT_EVENT` deliberately
# outranks the hypothetical guard, so without this a preventive question that says so plainly
# was read as a theft report. The `\s+` matters: "No, me robaron la tarjeta" -- a comma, an
# answer to a question rather than a negation -- must still count as an incident.
_NEGATED_INCIDENT = re.compile(
    r"\b(?:no|nunca|jam[aá]s|tampoco|ni)\s+(?:me\s+|se\s+me\s+)?$",
    re.IGNORECASE,
)


def _reports_an_incident(masked_text: str) -> bool:
    """True when the text describes an incident that is not being denied."""
    return any(
        not _NEGATED_INCIDENT.search(masked_text[max(0, match.start() - 40) : match.start()])
        for match in _INCIDENT_EVENT.finditer(masked_text)
    )


def category_from_keywords(text: str) -> Category | None:
    """First matching rule wins, matching `_fallback`'s original `next(...)` order."""
    lowered = text.lower()
    return next(
        (
            candidate
            for candidate, keywords in _CATEGORY_RULES
            if any(keyword in lowered for keyword in keywords)
        ),
        None,
    )


def sensitivity_floor(masked_text: str, category: Category) -> ConsultationLevel | None:
    """The lowest consultation level this request may be treated as, from its text alone.
    `None` means the text carries no signal and the classifier's own answer stands.

    This exists because `consultation_level` is load-bearing three times over -- it decides
    whether the kiosk confirms (`turn_nodes.requires_confirmation`), whether the case is
    ANONIMO or PENDIENTE (`confirmation_nodes.create_case_for_requirement`) and whether the
    answer comes from RAG (`InitialAttentionAgent.run`) -- so a single intermittent GENERAL
    from the model costs identification and human escalation in one HTTP request. The floor
    only ever raises: the model stays in charge of everything it is better at.
    """
    if category is Category.REPORTE_FRAUDE:
        # A fraud report is, by definition, about this person's own money. A purely
        # informational question about fraud classifies as CONSULTA_GENERAL instead.
        return ConsultationLevel.SENSIBLE
    if _reports_an_incident(masked_text):
        return ConsultationLevel.SENSIBLE
    preventive = bool(_HYPOTHETICAL.search(masked_text))
    if not preventive and _OWN_BANKING_OBJECT.search(masked_text):
        return ConsultationLevel.SENSIBLE
    if _OWN_FILE_OR_ACCESS.search(masked_text):
        return ConsultationLevel.PERSONALIZADA
    if (
        not preventive
        and category is Category.BANCA_DIGITAL
        and _DIGITAL_OPERATION_FAILURE.search(masked_text)
    ):
        return ConsultationLevel.PERSONALIZADA
    return None


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
        retrieval_queries: Sequence[str] | None = None,
    ) -> GroundedResponse | None:
        """`masked_query` is the question to answer; `retrieval_queries` are the phrasings
        to search with, which the caller widens when the question's wording is known to be a
        poor search key (see `finalize_nodes.attempt_grounding`). Defaults to searching with
        the question itself."""
        if level != ConsultationLevel.GENERAL:
            return None
        response = await self.knowledge.answer(
            db, case_id, category, masked_query, retrieval_queries
        )
        if response and not grounded_answer_is_natural(response.answer):
            logger.warning("grounded_answer_rejected", case_id=str(case_id), category=category)
            return None
        return response
