from app.domain.enums import Category, Priority
from app.services.agents import ClassificationAgent, PrioritizationAgent
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


def test_priority_rules_and_preferential_upgrade() -> None:
    agent = PrioritizationAgent()
    assert agent.run(Category.REPORTE_FRAUDE, "fraude", False) == Priority.CRITICO
    assert agent.run(Category.CONSULTA_GENERAL, "horarios", True) == Priority.MEDIO
    assert agent.run(Category.BLOQUEO_TARJETA, "bloqueo", True) == Priority.ALTO
