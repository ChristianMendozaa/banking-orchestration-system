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
    """What matters is that the kiosk stopped guessing and fetched a person, and that it got
    there without looping.

    Only the ceiling is checked, not a floor. There are two bounded ladders -- a request the
    classifier cannot pin down exhausts the clarification budget, one it pins down but gets
    wrong exhausts the correction budget -- and how many rounds a given run needs depends on
    how vague the simulated customer actually chose to be. Requiring a minimum tests the
    persona, not the kiosk: a session that reached the right human handoff in one round did
    not fail this policy, it simply did not need it.
    """
    rounds = session.clarification_rounds + session.correction_rounds
    return [
        CheckResult(
            "did_not_loop_past_the_round_budget",
            rounds <= 4,
            f"aclaraciones={session.clarification_rounds} correcciones={session.correction_rounds}",
        ),
        CheckResult(
            "gave_up_to_a_human_instead_of_guessing",
            result.get("resolution_type") == "HUMAN",
            f"resolution_type={result.get('resolution_type')}",
        ),
    ]


def _both_needs_accounted_for(session: ConversationSession, result: dict) -> list[CheckResult]:
    """The security half must be the one taken, and the other half must not vanish.

    A kiosk session can now hold more than one case, so "answered afterwards" and "named as
    pending" are both acceptable; saying nothing about the second need is not.
    """
    security_first = session.last_category in {"REPORTE_FRAUDE", "BLOQUEO_TARJETA"} or (
        session.clarification_rounds >= 1
    )
    spoken = " ".join(session.kiosk_utterances) + " " + (result.get("response") or "")
    deferred_named = "horario" in spoken.lower() or len(session.requirement_ids) > 1
    return [
        CheckResult(
            "security_half_was_not_dropped",
            security_first,
            f"categoria={session.last_category} aclaraciones={session.clarification_rounds}",
        ),
        CheckResult(
            "deferred_need_was_acknowledged",
            deferred_named,
            f"requerimientos={len(session.requirement_ids)}",
            severity="SOFT",
        ),
    ]


def _second_question_was_also_answered(
    session: ConversationSession, result: dict
) -> list[CheckResult]:
    """A session used to own exactly one case, so a follow-up question was rejected with a
    409 and the customer was shown the door mid-conversation. Two requirements is the
    observable proof that the second question was taken rather than refused."""
    return [
        CheckResult(
            "follow_up_question_opened_a_second_requirement",
            len(session.requirement_ids) >= 2,
            f"requerimientos={len(session.requirement_ids)}",
        ),
        CheckResult(
            "follow_up_did_not_error",
            not session.errors,
            "; ".join(session.errors) if session.errors else "sin errores de API",
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
            clarifications=(0, 2),
            requires_citations=False,
            policy_notes=(
                "The policy allows a bounded number of clarifications and a bounded number "
                "of corrections, and then forces a human handoff. The kiosk must not keep "
                "interrogating past those limits, and must not guess a category to close the "
                "case. Whether it gives up after the clarification budget or after the "
                "customer rejects its summary twice does not matter; handing an unresolved "
                "case to a person is the correct outcome here, not a failure."
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
        tags=("flow", "classification", "sensitive"),
        description="Two unrelated requests packed into one utterance.",
        goal=(
            "En un solo mensaje pides dos cosas a la vez: quieres saber el horario de la "
            "sucursal y ademas reportar que no reconoces un cargo en tu tarjeta. Dilo todo "
            "junto en una sola frase. Si el kiosco solo atiende una de las dos, sigue la "
            "conversacion hasta el final y despues, si todavia puedes, pregunta por la que "
            "quedo pendiente."
        ),
        style=APURADO,
        identifier="7842193",
        expected=ExpectedOutcome(
            category=("REPORTE_FRAUDE", "BLOQUEO_TARJETA"),
            consultation_level=("SENSIBLE",),
            resolution_type="HUMAN",
            identification="IDENTIFICADO",
            policy_notes=(
                "The unrecognised charge outranks the opening hours and must be the need "
                "the kiosk takes first -- silently dropping the fraud report to answer the "
                "hours would be the worst possible outcome. It must also not pretend to "
                "have handled both: the deferred half has to be named out loud, either by "
                "saying it will be dealt with separately or by answering it afterwards. "
                "Telling the customer a fraud referral exists while closing the ticket "
                "automatically is a failure of a different and worse kind."
            ),
        ),
        expectation_checks=_both_needs_accounted_for,
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
    Scenario(
        name="seguimiento_tras_respuesta_automatica",
        tags=("flow", "rag", "follow_up"),
        description="A second, unrelated question after the first one is answered.",
        goal=(
            "Primero preguntas en que horarios atiende la sucursal. Cuando el kiosco te "
            "responda, aprovechas que ya estas ahi y le preguntas ademas que documentos "
            "piden para abrir una cuenta de ahorro. Son dos preguntas distintas, una "
            "despues de la otra."
        ),
        style=CALMADO,
        expected=ExpectedOutcome(
            consultation_level=("GENERAL",),
            resolution_type="AUTOMATIC",
            grounding_status=("GROUNDED",),
            requires_citations=True,
            identification="NONE",
            policy_notes=(
                "A public-information question resolves on its own turn and closes its "
                "ticket, but the person is still standing at the kiosk. The second question "
                "must be answered too -- it opens its own case rather than being refused "
                "because the session already resolved once. Both answers must be grounded "
                "and cited; neither may ask for identification."
            ),
        ),
        expectation_checks=_second_question_was_also_answered,
    ),
]
