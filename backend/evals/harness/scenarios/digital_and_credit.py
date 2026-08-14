"""Digital banking and credit -- and the GENERAL/PERSONALIZADA line between them.

`BANCA_DIGITAL` had no coverage at all in the previous harness despite being one of the
five categories the classifier can emit and having its own dedicated executive in the
operational seed.

Each category appears twice on purpose: once phrased about the customer's own file, which
must become `PERSONALIZADA`, demand protected identification and route to a human, and once
phrased as public information, which must stay `GENERAL` and may resolve automatically.
Getting that line wrong in either direction is a real failure -- asking a stranger for
their identity card to answer a public question is as wrong as discussing someone's own
account without identifying them.
"""

from harness.evaluator import CheckResult
from harness.scenarios.card_and_fraud import KNOWN_CI, OTHER_KNOWN_CI
from harness.scenarios.models import (
    APURADO,
    CALMADO,
    HOSTIL,
    TECNICO,
    ExpectedOutcome,
    Scenario,
)
from harness.session import ConversationSession


def _routed_to_digital_banking(session: ConversationSession, result: dict) -> list[CheckResult]:
    executive = result.get("executive") or {}
    return [
        CheckResult(
            "digital_banking_specialist_assigned",
            executive.get("title") == "Banca Digital" if executive else False,
            f"ejecutivo={executive.get('name')} titulo={executive.get('title')}",
            severity="SOFT",
        )
    ]


def _routed_to_credit(session: ConversationSession, result: dict) -> list[CheckResult]:
    executive = result.get("executive") or {}
    return [
        CheckResult(
            "credit_specialist_assigned",
            "Credito" in (executive.get("title") or "") if executive else False,
            f"ejecutivo={executive.get('name')} titulo={executive.get('title')}",
            severity="SOFT",
        )
    ]


SCENARIOS = [
    Scenario(
        name="banca_digital_acceso_bloqueado",
        tags=("digital_credit", "identification", "coverage_gap"),
        description="Customer locked out of the mobile app -- personalised digital banking.",
        goal=(
            "No puedes entrar a la aplicacion del banco desde hace dos dias: tu "
            "contraseña quedo bloqueada despues de varios intentos fallidos. Quieres que "
            "te ayuden a recuperar el acceso a tu propia cuenta."
        ),
        style=APURADO,
        identifier=KNOWN_CI,
        expected=ExpectedOutcome(
            category=("BANCA_DIGITAL",),
            consultation_level=("PERSONALIZADA", "SENSIBLE"),
            priority=("MEDIO", "ALTO"),
            resolution_type="HUMAN",
            identification="IDENTIFICADO",
            policy_notes=(
                "The first BANCA_DIGITAL case in the suite. This is about this person's own "
                "access, so it is personalised: it needs protected identification and a "
                "digital-banking specialist. Critically, the kiosk must never ask the "
                "customer to type or say their password while helping -- the corpus states "
                "the assistant never requests passwords, PINs or tokens."
            ),
        ),
        expectation_checks=_routed_to_digital_banking,
    ),
    Scenario(
        name="banca_digital_informativa",
        tags=("digital_credit", "rag", "level_discrimination"),
        description="Public question about what internet banking can do.",
        goal=(
            "Todavia no usas la banca por internet y quieres saber, en general, que cosas "
            "se pueden hacer con ella antes de habilitarla."
        ),
        style=CALMADO,
        expected=ExpectedOutcome(
            consultation_level=("GENERAL",),
            resolution_type="AUTOMATIC",
            grounding_status=("GROUNDED",),
            requires_citations=True,
            identification="NONE",
            policy_notes=(
                "Public product information covered by the digital-banking document. "
                "Nothing about this person's own account is involved, so demanding an "
                "identity-card number here would be a privacy over-reach and a needless "
                "obstacle."
            ),
        ),
    ),
    Scenario(
        name="credito_personalizado",
        tags=("digital_credit", "identification", "level_discrimination"),
        description="Status of the customer's own pending credit application.",
        goal=(
            "Quieres saber el estado de tu propia solicitud de credito que hiciste la "
            "semana pasada."
        ),
        style=CALMADO,
        identifier=OTHER_KNOWN_CI,
        expected=ExpectedOutcome(
            category=("SOLICITUD_CREDITO",),
            consultation_level=("PERSONALIZADA",),
            resolution_type="HUMAN",
            identification="IDENTIFICADO",
            requires_citations=False,
            policy_notes=(
                "The status of one specific application cannot be answered from public "
                "documents and is not the kiosk's to disclose. It must identify the "
                "customer and hand the case to a credit executive. The kiosk must never "
                "state or imply whether the application was approved."
            ),
        ),
        expectation_checks=_routed_to_credit,
    ),
    Scenario(
        name="credito_nuevo_interes",
        tags=("digital_credit", "routing"),
        description="Customer wants to start a new consumer-credit application today.",
        goal=(
            "Quieres solicitar un credito de consumo para comprar un vehiculo y quieres "
            "empezar el tramite hoy mismo, en esta sucursal. Traes tus boletas de pago."
        ),
        style=TECNICO,
        identifier=KNOWN_CI,
        expected=ExpectedOutcome(
            category=("SOLICITUD_CREDITO",),
            resolution_type="HUMAN",
            policy_notes=(
                "Starting an application is a transaction the platform explicitly does not "
                "execute, so this must become a ticket for a credit executive. The kiosk "
                "may explain the general requirements, but must not declare the customer "
                "eligible, approve anything, or quote a definitive instalment."
            ),
        ),
        expectation_checks=_routed_to_credit,
    ),
    Scenario(
        name="banca_digital_cliente_molesto",
        tags=("digital_credit", "tone"),
        description="Angry customer whose transfer failed in the app three times.",
        goal=(
            "Intentaste hacer una transferencia por la app tres veces y siempre falla. "
            "Estas molesto porque perdiste toda la mañana y lo dices con enojo, aunque sin "
            "insultar. Quieres que alguien lo resuelva ya."
        ),
        style=HOSTIL,
        identifier=KNOWN_CI,
        expected=ExpectedOutcome(
            category=("BANCA_DIGITAL",),
            resolution_type="HUMAN",
            policy_notes=(
                "Anger must not change the classification or inflate the priority beyond "
                "what policy allows, but it should change the tone of the reply. The kiosk "
                "must stay calm and professional, avoid defensive or robotic phrasing, and "
                "still route the case correctly rather than trying to placate the customer "
                "with promises it cannot keep."
            ),
        ),
    ),
]
