"""Personas the Simulated Customer agent plays, each with its own expectation checks.

`expectation_checks` closures see the session *after* the conversation finishes and the
final GET result -- same shape the general policy checks in `evaluator.py` see -- so a
persona can assert things specific to its scenario (e.g. "this should end up as
BLOQUEO_TARJETA or REPORTE_FRAUDE") on top of the four general policy checks every
persona gets automatically.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from harness.evaluator import CheckResult
from harness.session import ConversationSession

ExpectationChecks = Callable[[ConversationSession, dict], list[CheckResult]]


@dataclass(frozen=True, slots=True)
class Persona:
    name: str
    goal: str
    preferential_attention: bool = False
    expectation_checks: ExpectationChecks = field(default=lambda session, result: [])


def _stolen_card_checks(session: ConversationSession, result: dict) -> list[CheckResult]:
    return [
        CheckResult(
            "category_is_card_block_or_fraud",
            session.last_category in {"BLOQUEO_TARJETA", "REPORTE_FRAUDE"},
            f"category={session.last_category}",
        ),
        CheckResult(
            "resolution_is_human",
            result.get("resolution_type") == "HUMAN",
            f"resolution_type={result.get('resolution_type')}",
        ),
    ]


def _fraud_report_checks(session: ConversationSession, result: dict) -> list[CheckResult]:
    return [
        CheckResult(
            "category_is_fraud",
            session.last_category == "REPORTE_FRAUDE",
            f"category={session.last_category}",
        ),
        CheckResult(
            "priority_is_critical",
            result.get("priority") == "CRITICO",
            f"priority={result.get('priority')}",
        ),
    ]


def _general_hours_checks(session: ConversationSession, result: dict) -> list[CheckResult]:
    return [
        CheckResult(
            "category_is_general",
            session.last_category == "CONSULTA_GENERAL",
            f"category={session.last_category}",
        ),
        CheckResult(
            "at_least_one_clarification",
            session.clarification_rounds >= 1,
            f"rounds={session.clarification_rounds}",
        ),
    ]


def _credit_inquiry_checks(session: ConversationSession, result: dict) -> list[CheckResult]:
    return [
        CheckResult(
            "category_is_credit",
            session.last_category == "SOLICITUD_CREDITO",
            f"category={session.last_category}",
        ),
        CheckResult(
            "resolution_is_human",
            result.get("resolution_type") == "HUMAN",
            f"resolution_type={result.get('resolution_type')}",
        ),
    ]


def _persistently_vague_checks(session: ConversationSession, result: dict) -> list[CheckResult]:
    return [
        CheckResult(
            "clarification_limit_reached_then_forced_human",
            session.clarification_rounds >= 1 and result.get("resolution_type") == "HUMAN",
            f"rounds={session.clarification_rounds} "
            f"resolution_type={result.get('resolution_type')}",
        ),
    ]


PERSONAS: list[Persona] = [
    Persona(
        name="tarjeta_robada_angustiado",
        goal=(
            "Te acaban de robar la tarjeta de debito hace unos minutos y estas muy "
            "angustiado. Quieres bloquearla de inmediato antes de que la usen."
        ),
        expectation_checks=_stolen_card_checks,
    ),
    Persona(
        name="fraude_movimiento_no_reconocido",
        goal=(
            "Revisaste tu estado de cuenta y encontraste un movimiento que no reconoces "
            "ni realizaste. Quieres reportarlo como fraude."
        ),
        expectation_checks=_fraud_report_checks,
    ),
    Persona(
        name="consulta_horarios_ambigua",
        goal=(
            "Primero di una respuesta vaga como 'quiero saber algo del banco' sin "
            "especificar que necesitas. Solo cuando el kiosco te pida aclarar, explica que "
            "quieres saber el horario de atencion de la sucursal."
        ),
        expectation_checks=_general_hours_checks,
    ),
    Persona(
        name="consulta_credito_personalizada",
        goal=(
            "Quieres saber el estado de tu propia solicitud de credito que hiciste la "
            "semana pasada."
        ),
        expectation_checks=_credit_inquiry_checks,
    ),
    Persona(
        name="ambiguo_persistente",
        goal=(
            "Responde de forma vaga e imprecisa a cada pregunta, incluidas las "
            "aclaraciones del kiosco -- nunca describas con claridad que necesitas, "
            "incluso si te piden aclarar varias veces."
        ),
        expectation_checks=_persistently_vague_checks,
    ),
]
