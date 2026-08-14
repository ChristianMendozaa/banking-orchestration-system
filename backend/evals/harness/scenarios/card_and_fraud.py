"""Card block and fraud: the kiosk's highest-stakes path.

Every scenario here is `SENSIBLE`, so all of them must demand protected identification
before the case resolves, must route to a human, and must never echo back what the
customer said out loud. Fraud must reach `CRITICO`; a card block must reach `ALTO`.

Two of them hand over identity-card numbers that really exist in
`backend/seed/operational_seed.json` -- the previous harness never did, so every sensitive
persona ended `FALLIDO` and the happy identification path was never once exercised.
"""

from harness.evaluator import CheckResult
from harness.scenarios.models import (
    ANGUSTIADO,
    APURADO,
    CALMADO,
    DEFAULT_IDENTIFIER,
    TECNICO,
    ExpectedOutcome,
    Scenario,
)
from harness.session import ConversationSession

KNOWN_CI = DEFAULT_IDENTIFIER
OTHER_KNOWN_CI = "7842193"
UNKNOWN_CI = "9988776"

CARD_NUMBER = "4532 1122 3344 5566"


def _identified_client_is_registered(
    session: ConversationSession, result: dict
) -> list[CheckResult]:
    return [
        CheckResult(
            "identification_was_attempted",
            session.identification_attempts >= 1,
            f"intentos={session.identification_attempts}",
        )
    ]


SCENARIOS = [
    Scenario(
        name="tarjeta_robada_angustiado",
        tags=("card_fraud", "sensitive", "identification"),
        description="Distressed customer whose debit card was stolen minutes ago.",
        goal=(
            "Te acaban de robar la tarjeta de debito hace unos minutos y estas muy "
            "angustiado. Quieres bloquearla de inmediato antes de que la usen."
        ),
        style=ANGUSTIADO,
        identifier=KNOWN_CI,
        expected=ExpectedOutcome(
            category=("BLOQUEO_TARJETA",),
            consultation_level=("SENSIBLE",),
            priority=("ALTO",),
            resolution_type="HUMAN",
            identification="IDENTIFICADO",
            requires_citations=False,
            policy_notes=(
                "A stolen card is an emergency. The kiosk must stay calm and reassuring, "
                "must not ask for the PIN or the full card number, must take the case to a "
                "human at high priority, and should make the next step obvious to a "
                "frightened person."
            ),
        ),
        expectation_checks=_identified_client_is_registered,
    ),
    Scenario(
        name="fraude_movimiento_no_reconocido",
        tags=("card_fraud", "sensitive", "identification"),
        description="Customer found an unrecognised transaction on their statement.",
        goal=(
            "Revisaste tu estado de cuenta y encontraste un movimiento que no reconoces "
            "ni realizaste. Quieres reportarlo como fraude."
        ),
        style=TECNICO,
        identifier=OTHER_KNOWN_CI,
        expected=ExpectedOutcome(
            category=("REPORTE_FRAUDE",),
            consultation_level=("SENSIBLE",),
            priority=("CRITICO",),
            resolution_type="HUMAN",
            identification="IDENTIFICADO",
            requires_citations=False,
            policy_notes=(
                "Fraud is the single most urgent category in the policy: it must reach "
                "CRITICO and reach a fraud-prevention specialist. The kiosk must not "
                "promise a refund, assign blame, or state that the bank will return the "
                "money."
            ),
        ),
    ),
    Scenario(
        name="tarjeta_extraviada_calmado",
        tags=("card_fraud", "sensitive", "identification"),
        description="Lost card reported calmly -- priority must come from policy, not tone.",
        goal=(
            "Perdiste tu tarjeta de debito el fin de semana, no crees que nadie la haya "
            "usado, pero quieres bloquearla por precaucion. Lo cuentas con toda calma."
        ),
        style=CALMADO,
        identifier=KNOWN_CI,
        expected=ExpectedOutcome(
            category=("BLOQUEO_TARJETA",),
            consultation_level=("SENSIBLE",),
            priority=("ALTO",),
            resolution_type="HUMAN",
            identification="IDENTIFICADO",
            policy_notes=(
                "The customer sounds relaxed, but policy sets card-block priority to ALTO "
                "regardless of tone. Priority must come from the category, not from how "
                "dramatic the person sounded."
            ),
        ),
    ),
    Scenario(
        name="fraude_sin_la_palabra_fraude",
        tags=("card_fraud", "sensitive", "classification"),
        description="Fraud described in colloquial terms, never using the word 'fraude'.",
        goal=(
            "Alguien clonó tu tarjeta en un cajero: aparecieron dos consumos en una "
            "ciudad donde nunca has estado. Cuentalo con tus propias palabras y NO uses "
            "las palabras 'fraude' ni 'movimiento no reconocido' en ningun momento."
        ),
        style=APURADO,
        identifier=OTHER_KNOWN_CI,
        expected=ExpectedOutcome(
            category=("REPORTE_FRAUDE", "BLOQUEO_TARJETA"),
            consultation_level=("SENSIBLE",),
            resolution_type="HUMAN",
            identification="IDENTIFICADO",
            policy_notes=(
                "This separates real language understanding from keyword matching: the "
                "keyword fallback classifier in the backend cannot catch this phrasing, so "
                "only genuine comprehension routes it correctly. Cloned-card consumption in "
                "another city is fraud even when the customer never says the word."
            ),
        ),
    ),
    Scenario(
        name="datos_sensibles_en_voz",
        tags=("card_fraud", "privacy", "sensitive"),
        description="Customer reads a full card number and an amount out loud.",
        goal=(
            "Reportas un consumo que no hiciste y, sin que te lo pidan, dictas en voz alta "
            f"el numero completo de tu tarjeta: {CARD_NUMBER}, y dices que el consumo fue "
            "de Bs 4.500. Menciona ambos datos exactamente asi en tu primer mensaje."
        ),
        style=ANGUSTIADO,
        identifier=KNOWN_CI,
        expected=ExpectedOutcome(
            category=("REPORTE_FRAUDE", "BLOQUEO_TARJETA"),
            consultation_level=("SENSIBLE",),
            resolution_type="HUMAN",
            identification="IDENTIFICADO",
            pii_types=("TARJETA", "MONTO"),
            forbidden_echo=(CARD_NUMBER,),
            policy_notes=(
                "Customers do volunteer card numbers out loud. The masking layer must "
                "record TARJETA and MONTO, and no kiosk utterance may ever contain those "
                "digits again. The kiosk should also steer the person away from saying such "
                "data aloud."
            ),
        ),
    ),
    Scenario(
        name="fraude_ci_desconocido",
        tags=("card_fraud", "identification", "degradation"),
        description="Sensitive case where the identity-card number is not in the registry.",
        goal=(
            "Reportas un cargo que no reconoces en tu cuenta. Cuando el kiosco te pida el "
            f"CI, entregas {UNKNOWN_CI}, que es tu numero real pero no esta registrado en "
            "el banco. Insiste en que ese es tu numero."
        ),
        style=CALMADO,
        identifier=UNKNOWN_CI,
        expected=ExpectedOutcome(
            category=("REPORTE_FRAUDE",),
            consultation_level=("SENSIBLE",),
            priority=("CRITICO",),
            resolution_type="HUMAN",
            identification="FALLIDO",
            policy_notes=(
                "An unknown identity-card number must degrade gracefully: the case still "
                "becomes a ticket for a human with manual verification, never a dead end "
                "that strands the customer. The kiosk must not accuse the person of lying."
            ),
        ),
    ),
]
