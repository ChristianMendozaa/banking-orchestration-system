from collections import defaultdict

from app.db.models import Executive, ExecutiveSkill
from app.domain.enums import (
    Category,
    ConsultationLevel,
    ExecutiveStatus,
    Priority,
)
from app.services.agents import ClassificationAgent, DerivationAgent, PrioritizationAgent
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


async def test_fallback_classifier_is_conservative(settings) -> None:
    agent = ClassificationAgent(settings, provider=None)
    result = await agent.run("Tengo un movimiento no reconocido y posible fraude")
    assert result.category == Category.REPORTE_FRAUDE
    assert result.security_incident is True


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
    assert selected is semantic_match
