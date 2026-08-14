"""Preferential attention and customers the kiosk must not leave behind.

`preferential_attention` is a flag the kiosk UI sets at session creation for customers
entitled to priority attention (older adults, pregnant women, people with disabilities).
`PrioritizationAgent` raises any `BAJO` or `MEDIO` case one level for them and leaves
`ALTO`/`CRITICO` untouched -- a rule with no coverage whatsoever in the previous harness.

The remaining scenarios are about comprehension rather than routing: a self-service kiosk
that only works for articulate, confident speakers is not accessible.
"""

from harness.evaluator import CheckResult
from harness.scenarios.models import (
    ADULTO_MAYOR,
    DISPERSO,
    PARCO,
    ExpectedOutcome,
    Scenario,
)
from harness.session import ConversationSession


def _priority_was_raised(session: ConversationSession, result: dict) -> list[CheckResult]:
    """A general inquiry is BAJO by default; preferential attention must lift it to MEDIO.

    Only checked when the case actually reached a human -- an automatically resolved
    inquiry closes its own ticket and the priority never affects anyone's queue.
    """
    if result.get("resolution_type") != "HUMAN":
        return [
            CheckResult.skip(
                "preferential_attention_raised_priority",
                "la consulta se resolvio automaticamente",
            )
        ]
    return [
        CheckResult(
            "preferential_attention_raised_priority",
            result.get("priority") in {"MEDIO", "ALTO", "CRITICO"},
            f"priority={result.get('priority')} (sin preferencia seria BAJO)",
        )
    ]


SCENARIOS = [
    Scenario(
        name="atencion_preferencial_adulto_mayor",
        tags=("accessibility", "priority", "coverage_gap"),
        description="Preferential-attention session with an otherwise low-priority need.",
        goal=(
            "Eres una persona de la tercera edad y vienes a preguntar como hacer para que "
            "te depositen tu renta en una cuenta del banco. Hablas despacio y con calma."
        ),
        style=ADULTO_MAYOR,
        preferential_attention=True,
        expected=ExpectedOutcome(
            policy_notes=(
                "This session was created with preferential attention. If the case reaches "
                "a human, policy requires its priority to be raised one level above the "
                "BAJO a general inquiry would otherwise get. The reply should also be "
                "unhurried and free of jargon."
            ),
        ),
        expectation_checks=_priority_was_raised,
    ),
    Scenario(
        name="preferencial_caso_critico",
        tags=("accessibility", "priority"),
        description="Preferential attention on a fraud case -- already at the ceiling.",
        goal=(
            "Eres una persona con discapacidad visual y vienes acompañado. Detectaste un "
            "cobro que no reconoces en tu cuenta y quieres reportarlo."
        ),
        style=ADULTO_MAYOR,
        preferential_attention=True,
        identifier="6735666",
        expected=ExpectedOutcome(
            category=("REPORTE_FRAUDE",),
            priority=("CRITICO",),
            resolution_type="HUMAN",
            identification="IDENTIFICADO",
            policy_notes=(
                "Fraud is already CRITICO and the preferential bump must not push it past "
                "the ceiling -- the operating manual states preferential attention raises "
                "low and medium cases without overtaking critical security cases. The reply "
                "must also work for someone who cannot read the screen: everything "
                "essential has to be in the spoken text."
            ),
        ),
    ),
    Scenario(
        name="dificultad_para_expresarse",
        tags=("accessibility", "comprehension"),
        description="Long, disorganised account with the real need buried at the end.",
        goal=(
            "Cuentas una historia larga y desordenada: que viniste en micro, que la fila "
            "estaba larga, que tu hijo te dijo que vengas, que el mes pasado te cobraron "
            "algo raro. Solo al final mencionas lo que necesitas: que no te llega el "
            "extracto de tu cuenta y quieres que te lo expliquen."
        ),
        style=DISPERSO,
        identifier="7842193",
        expected=ExpectedOutcome(
            policy_notes=(
                "The real need arrives last, after a lot of noise. The kiosk must find it "
                "instead of latching onto the first thing mentioned, and the summary it "
                "reads back must be something this customer would recognise as their own "
                "request. Comprehension is the whole test."
            ),
        ),
    ),
    Scenario(
        name="cliente_no_entiende_la_pregunta",
        tags=("accessibility", "comprehension"),
        description="Customer does not understand the clarification question and says so.",
        goal=(
            "Quieres 'arreglar lo de tu tarjeta' sin dar mas detalles. Cuando el kiosco te "
            "pregunte algo, responde que no entendiste la pregunta y pide que te la "
            "expliquen de otra forma, mas simple."
        ),
        style=PARCO,
        expected=ExpectedOutcome(
            resolution_type="HUMAN",
            policy_notes=(
                "When someone says they did not understand, repeating the same wording is "
                "a failure. The kiosk should simplify or route to a person. It must never "
                "leave the customer stuck in a loop with no way out."
            ),
        ),
    ),
]
