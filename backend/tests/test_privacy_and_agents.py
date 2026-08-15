from collections import defaultdict

from app.db.models import Executive, ExecutiveSkill
from app.domain.enums import (
    Category,
    ConsultationLevel,
    ExecutiveStatus,
    Priority,
)
from app.domain.schemas import ClassificationDecision
from app.services.agents import (
    ClassificationAgent,
    DerivationAgent,
    PrioritizationAgent,
    customer_facing_text_is_natural,
    grounded_answer_is_natural,
)
from app.services.pii import PIIMaskingService


def test_pii_masking_removes_sensitive_values() -> None:
    service = PIIMaskingService()
    result = service.mask(
        "Mi correo es ana@example.com, telefono 71234567, tarjeta 4111 1111 1111 1111 "
        "y el monto es Bs. 4500"
    )
    assert "ana@example.com" not in result.masked_text
    assert "71234567" not in result.masked_text
    assert "4111" not in result.masked_text
    assert "4500" not in result.masked_text
    assert {"EMAIL", "TELEFONO", "TARJETA", "MONTO"}.issubset(result.counts)


def test_grounded_answer_naturalness_allows_third_person_verbs_about_the_bank() -> None:
    """`grounded_answer_is_natural` must be narrower than `customer_facing_text_is_natural`:
    a multi-sentence RAG answer legitimately says "el banco puede pedir..." or "la tasa
    depende de un análisis...", which InitialAttentionAgent used to discard silently because
    it reused the stricter predicate meant for the kiosk's own short, first-person text."""
    plausible_credit_answer = (
        "Para un crédito de consumo, el banco puede solicitar tu documento de identidad "
        "vigente y tus últimas boletas de pago. La tasa depende del análisis crediticio y "
        "el plazo se define caso por caso."
    )
    assert customer_facing_text_is_natural(plausible_credit_answer) is False
    assert grounded_answer_is_natural(plausible_credit_answer) is True


def test_grounded_answer_naturalness_still_rejects_third_person_customer_references() -> None:
    assert grounded_answer_is_natural("El cliente debe presentar su documento de identidad.") is (
        False
    )
    assert grounded_answer_is_natural("Usted debe presentar su documento de identidad.") is False


async def test_fallback_classifier_is_conservative(settings) -> None:
    agent = ClassificationAgent(settings, provider=None)
    result = await agent.run("Tengo un movimiento no reconocido y posible fraude")
    assert result.category == Category.REPORTE_FRAUDE
    assert result.security_incident is True


async def test_classifier_replaces_internal_or_formal_customer_language(settings) -> None:
    class Provider:
        async def classify(self, _: str) -> ClassificationDecision:
            return ClassificationDecision(
                summary="La persona reporta un movimiento no reconocido",
                customer_summary="El usuario necesita denunciar fraude en su tarjeta.",
                category=Category.REPORTE_FRAUDE,
                consultation_level=ConsultationLevel.SENSIBLE,
                confidence=0.95,
                ambiguous=False,
            )

    result = await ClassificationAgent(settings, Provider()).run("movimiento no reconocido")
    assert result.summary == "La persona reporta un movimiento no reconocido"
    assert result.customer_summary == (
        "Necesitas reportar un posible fraude o un movimiento no reconocido."
    )


async def test_classifier_replaces_a_formal_clarification_question(settings) -> None:
    class Provider:
        async def classify(self, _: str) -> ClassificationDecision:
            return ClassificationDecision(
                summary="Consulta bancaria ambigua",
                customer_summary="Necesitas orientación sobre una consulta bancaria.",
                category=Category.CONSULTA_GENERAL,
                consultation_level=ConsultationLevel.GENERAL,
                confidence=0.4,
                ambiguous=True,
                clarification_question="¿Puede contarme qué trámite necesita?",
            )

    result = await ClassificationAgent(settings, Provider()).run("Necesito ayuda")
    assert result.clarification_question == (
        "¿Me cuentas brevemente qué trámite o problema necesitas resolver?"
    )


async def test_product_information_is_general_even_for_credit_category(settings) -> None:
    agent = ClassificationAgent(settings, provider=None)
    result = await agent.run("¿Qué requisitos necesito para solicitar un crédito de consumo?")
    assert result.category == Category.SOLICITUD_CREDITO
    assert result.consultation_level == ConsultationLevel.GENERAL


def test_priority_rules_and_preferential_upgrade() -> None:
    agent = PrioritizationAgent()
    assert agent.run(Category.REPORTE_FRAUDE, "fraude", False) == Priority.CRITICO
    assert agent.run(Category.CONSULTA_GENERAL, "horarios", True) == Priority.MEDIO
    assert agent.run(Category.BLOQUEO_TARJETA, "bloqueo", True) == Priority.ALTO


def test_stolen_card_urgency_never_outranks_the_fraud_ceiling() -> None:
    """Regression test for the priority-ladder operator-precedence bug: `A or B or C and D`
    parsed as `A or B or (C and D)`, so any category paired with `security_incident and
    urgency_detected` -- which the classifier sets together for a stolen card -- jumped
    straight to CRITICO and made the BLOQUEO_TARJETA -> ALTO branch unreachable."""
    agent = PrioritizationAgent()
    assert (
        agent.run(
            Category.BLOQUEO_TARJETA,
            "tarjeta robada",
            False,
            urgency_detected=True,
            security_incident=True,
        )
        == Priority.ALTO
    )
    assert (
        agent.run(
            Category.REPORTE_FRAUDE,
            "fraude",
            False,
            urgency_detected=True,
            security_incident=True,
        )
        == Priority.CRITICO
    )
    assert (
        agent.run(Category.CONSULTA_GENERAL, "consulta urgente", False, urgency_detected=True)
        == Priority.MEDIO
    )


async def test_derivation_uses_semantic_similarity_before_experience() -> None:
    semantic_match = Executive(
        display_name="Coincidencia semántica",
        title="Ejecutivo",
        window_number="V1",
        status=ExecutiveStatus.DISPONIBLE,
    )
    semantic_match.skills = [
        ExecutiveSkill(
            category=Category.REPORTE_FRAUDE,
            description="movimientos no reconocidos",
            experience_level=1,
        )
    ]
    experience_only = Executive(
        display_name="Solo experiencia",
        title="Ejecutivo",
        window_number="V2",
        status=ExecutiveStatus.DISPONIBLE,
    )
    experience_only.skills = [
        ExecutiveSkill(
            category=Category.REPORTE_FRAUDE,
            description="fraude genérico",
            experience_level=5,
        )
    ]

    class Repository:
        async def available(self, _):
            return [semantic_match, experience_only]

        async def active_loads(self, _):
            return defaultdict(int)

    class Provider:
        async def embedding(self, text: str) -> list[float]:
            return [1.0, 0.0] if "movimiento" in text else [0.0, 1.0]

    selected = await DerivationAgent(Provider(), Repository()).run(
        None,
        Category.REPORTE_FRAUDE,
        "movimiento no reconocido",
    )
    assert selected is not None
    assert selected.executive is semantic_match
    assert selected.active_load == 0
