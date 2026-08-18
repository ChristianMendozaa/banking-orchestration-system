"""Conversation control: clarification, correction, topic changes, dead ends.

These scenarios exercise the parts of the state machine a well-behaved customer never
reaches. `correccion_de_resumen` in particular drives `POST /confirmation` with
`confirmed=false` -- the correction loop that returns the session to `LISTENING` and
increments `correction_count` -- which the previous harness never touched at all, despite
it being one of only three ways a kiosk session can move backwards.
"""

from harness.evaluator import CheckResult
from harness.scenarios.models import (
    APURADO,
    CALMADO,
    DISPERSO,
    PARCO,
    ExpectedOutcome,
    Scenario,
)
from harness.session import ConversationSession


def _forced_human_after_limit(session: ConversationSession, result: dict) -> list[CheckResult]:
    return [
        CheckResult(
            "clarification_limit_exhausted",
            session.clarification_rounds >= 2,
            f"rounds={session.clarification_rounds}",
        ),
        CheckResult(
            "gave_up_to_a_human_instead_of_guessing",
            result.get("resolution_type") == "HUMAN",
            f"resolution_type={result.get('resolution_type')}",
        ),
    ]


def _correction_produced_a_new_requirement(
    session: ConversationSession, result: dict
) -> list[CheckResult]:
    return [
        CheckResult(
            "correction_created_a_second_requirement",
            len(session.requirement_ids) >= 2,
            f"requirements={len(session.requirement_ids)}",
        ),
        CheckResult(
            "final_case_matches_the_corrected_intent",
            session.last_category == "BLOQUEO_TARJETA",
            f"categoria final={session.last_category}",
        ),
    ]


SCENARIOS = [
    Scenario(
        name="ambiguo_persistente",
        tags=("flow", "clarification"),
        description="Customer stays vague through every clarification the policy allows.",
        goal=(
            "Responde de forma vaga e imprecisa a cada pregunta, incluidas las "
            "aclaraciones del kiosco -- nunca describas con claridad que necesitas, "
            "incluso si te piden aclarar varias veces."
        ),
        style=DISPERSO,
        expected=ExpectedOutcome(
            resolution_type="HUMAN",
            clarifications=(2, 2),
            requires_citations=False,
            policy_notes=(
                "The policy allows exactly MAX_CLARIFICATIONS questions and then forces a "
                "human handoff. The kiosk must not keep interrogating past the limit, and "
                "must not guess a category to close the case. Handing an unresolved case to "
                "a person is the correct outcome here, not a failure."
            ),
        ),
        expectation_checks=_forced_human_after_limit,
    ),
    Scenario(
        name="correccion_de_resumen",
        tags=("flow", "correction", "coverage_gap"),
        description="Customer rejects the kiosk's summary and restates a different need.",
        goal=(
            "Empieza diciendo que no puedes acceder a tu cuenta de banca digital porque "
            "se te olvido la clave. Cuando el kiosco te proponga su resumen y te pida "
            "confirmarlo, RECHAZALO con send_confirmation(confirmed=false) porque en "
            "realidad te equivocaste. Despues explica lo que de verdad necesitas: "
            "bloquear tu tarjeta de debito porque la perdiste. Confirma solo el segundo "
            "resumen."
        ),
        style=CALMADO,
        identifier="6735666",
        expected=ExpectedOutcome(
            category=("BLOQUEO_TARJETA",),
            resolution_type="HUMAN",
            corrections=1,
            identification="IDENTIFICADO",
            policy_notes=(
                "The correction loop is what makes confirmation meaningful. Rejecting the "
                "summary must return the session to listening and start a fresh "
                "requirement; the final case must reflect the corrected intent (card block), "
                "not the abandoned one (digital banking access). The kiosk must accept the "
                "correction gracefully rather than arguing with the customer."
            ),
        ),
        expectation_checks=_correction_produced_a_new_requirement,
    ),
    Scenario(
        name="multi_intencion",
        tags=("flow", "classification"),
        description="Two unrelated requests packed into one utterance.",
        goal=(
            "En un solo mensaje pides dos cosas a la vez: quieres saber el horario de la "
            "sucursal y ademas reportar que no reconoces un cargo en tu tarjeta. Dilo todo "
            "junto en una sola frase."
        ),
        style=APURADO,
        identifier="7842193",
        expected=ExpectedOutcome(
            policy_notes=(
                "One session produces one case, so the kiosk has to either ask which need "
                "to handle first or take the more serious one. Silently dropping the fraud "
                "report to answer the opening hours would be the worst possible outcome: "
                "the security-relevant half must not be lost. Judge whether the kiosk "
                "noticed there were two requests at all."
            ),
        ),
        expectation_checks=lambda session, result: [
            CheckResult(
                "security_half_was_not_dropped",
                session.last_category in {"REPORTE_FRAUDE", "BLOQUEO_TARJETA"}
                or session.clarification_rounds >= 1,
                f"categoria={session.last_category} aclaraciones={session.clarification_rounds}",
            )
        ],
    ),
    Scenario(
        name="cambio_de_tema",
        tags=("flow", "clarification"),
        description="Customer switches from a trivial question to an emergency mid-session.",
        goal=(
            "Empieza preguntando por el horario de la sucursal. Si el kiosco te pide "
            "aclarar o confirmar, interrumpe y di que acabas de darte cuenta de que no "
            "tienes tu tarjeta, que te la robaron, y que eso es lo urgente ahora."
        ),
        style=DISPERSO,
        identifier="6735666",
        expected=ExpectedOutcome(
            policy_notes=(
                "The need that matters is the last one stated, and it is an emergency. A "
                "session that ends up ticketed for opening hours while the customer said "
                "their card was stolen has failed the person in front of it, whatever the "
                "state machine says. Judge whether the kiosk followed the change of topic."
            ),
        ),
        expectation_checks=lambda session, result: [
            CheckResult(
                "followed_the_topic_change",
                session.last_category in {"BLOQUEO_TARJETA", "REPORTE_FRAUDE"},
                f"categoria final={session.last_category}",
            )
        ],
    ),
    Scenario(
        name="respuestas_monosilabicas",
        tags=("flow", "clarification"),
        description="Customer answers only in monosyllables.",
        goal=(
            "Responde unicamente con monosilabos: 'si', 'no', 'no se', 'mas o menos'. "
            "Nunca expliques nada por tu cuenta, ni siquiera cuando te lo pidan "
            "directamente."
        ),
        style=PARCO,
        expected=ExpectedOutcome(
            resolution_type="HUMAN",
            clarifications=(1, 2),
            policy_notes=(
                "Some people simply will not talk to a machine. The kiosk must recognise "
                "the dead end within the clarification limit and route to a person instead "
                "of looping. The clarification questions it does ask should be simple and "
                "closed enough that even a monosyllabic answer moves things forward."
            ),
        ),
    ),
]
