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


def _outcome_was_voiced(outcome: dict, spoken: str) -> bool:
    ticket = (outcome.get("ticket") or {}).get("number")
    if ticket is not None and str(ticket) in spoken:
        return True
    answer = (outcome.get("grounding_detail") or {}).get("spoken") or outcome.get("response")
    return bool(answer) and answer[:40] in spoken


def _both_needs_accounted_for(session: ConversationSession, result: dict) -> list[CheckResult]:
    """The security half must be the one taken, and the other half must not vanish.

    A kiosk session can now hold more than one case, so "answered afterwards" and "named as
    pending" are both acceptable; saying nothing about the second need is not.
    """
    security_first = session.last_category in {"REPORTE_FRAUDE", "BLOQUEO_TARJETA"} or (
        session.clarification_rounds >= 1
    )
    spoken = " ".join(session.kiosk_utterances) + " " + (result.get("response") or "")
    outcomes = result.get("outcomes") or []
    # The second need counts as acknowledged when what the kiosk said carries its own
    # outcome -- its answer or its ticket number. Looking for the word "horario" failed a
    # kiosk that answered "atiende de lunes a viernes de 08:30 a 19:00" to a customer who
    # had asked "¿a qué hora abre?" (2026-10-21).
    deferred_named = len(outcomes) > 1 and all(
        _outcome_was_voiced(outcome, spoken) for outcome in outcomes[1:]
    )
    return [
        CheckResult(
            "security_half_was_not_dropped",
            security_first,
            f"categoria={session.last_category} aclaraciones={session.clarification_rounds}",
        ),
        CheckResult(
            "deferred_need_was_acknowledged",
            deferred_named,
            f"requerimientos={len(session.requirement_ids)} outcomes={len(outcomes)}",
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


async def drive_thanks_after_an_answer(session: ConversationSession) -> list[CheckResult]:
    """Scripted so the goodbye is always said, word for word.

    On 2026-10-20 the simulated customer happened to answer an automatic reply with "Ya
    está, muchas gracias, eso era todo", and the kiosk opened a ticket for it. Whether the
    customer model says goodbye is its own business; whether the kiosk handles a goodbye
    is the kiosk's, so this scenario does not leave it to chance.
    """
    await session.send_turn(
        "Buenas, ¿cuál es el horario de atención de esta sucursal?", is_clarification=False
    )
    answered = session.exchanges[-1].response if session.exchanges else {}
    first_result = answered.get("result") or {}
    await session.send_turn("Listo, muchas gracias, eso era todo.", is_clarification=False)
    goodbye = session.exchanges[-1].response if len(session.exchanges) > 1 else {}
    result = goodbye.get("result") or {}
    plan = goodbye.get("speech_plan") or {}
    return [
        CheckResult(
            "question_is_answered_before_the_goodbye",
            first_result.get("resolution_type") == "AUTOMATIC",
            f"resolution={first_result.get('resolution_type')}",
        ),
        CheckResult(
            "goodbye_opens_nothing",
            goodbye.get("next_action") == "COMPLETE"
            and result.get("ticket") is None
            and len(session.outcomes) == 1,
            f"next_action={goodbye.get('next_action')} ticket={result.get('ticket')} "
            f"casos={len(session.outcomes)}",
        ),
        CheckResult(
            "goodbye_is_answered_with_a_goodbye",
            plan.get("intent") == "FAREWELL" and result.get("conversation_can_continue") is False,
            f"intent={plan.get('intent')} "
            f"puede_continuar={result.get('conversation_can_continue')}",
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
                "A public-information question resolves on its own turn without creating a "
                "ticket, but the person is still standing at the kiosk. The second question "
                "must be answered too -- it opens its own case rather than being refused "
                "because the session already resolved once. Both answers must be grounded "
                "and cited; neither may ask for identification."
            ),
        ),
        expectation_checks=_second_question_was_also_answered,
    ),
    Scenario(
        name="despedida_tras_respuesta",
        tags=("flow", "rag", "closing"),
        description="The customer says thanks and goodbye after an automatic answer.",
        goal=(
            "Preguntas el horario de la sucursal y, cuando el kiosco responde, das las "
            "gracias y te despides. Guionizado: ver drive_thanks_after_an_answer."
        ),
        style=CALMADO,
        script=drive_thanks_after_an_answer,
        expected=ExpectedOutcome(
            consultation_level=("GENERAL",),
            resolution_type="AUTOMATIC",
            grounding_status=("GROUNDED",),
            requires_citations=True,
            identification="NONE",
            policy_notes=(
                "A thank-you after an answered question is the end of the conversation, not "
                "a new request. The kiosk must answer the question from the corpus, then "
                "say goodbye without opening a second case, a ticket or another question, "
                "and without reading the answer again."
            ),
        ),
    ),
]
