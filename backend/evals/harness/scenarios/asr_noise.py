"""ASR-noise scenarios: what the kiosk does when the transcript is wrong.

Every other group in this catalog hands the backend a clean sentence, because the simulated
customer writes text. A real customer speaks, and the voice layer transcribes -- and on
2026-08-19 a live kiosk session classified "Quiero portar el juego de mi tarjeta de debito"
for someone who had said "Quiero reportar el robo de mi tarjeta de debito". The orchestrator
behaved correctly on that input; it was simply given the wrong input, and no scenario in this
catalog could have caught it because none of them can produce a wrong one.

These scripts drive the API directly with fixed, deliberately corrupted transcripts -- the
kind a Spanish ASR actually produces -- and assert the two properties that matter when the
words are unreliable:

1. **Corruption must not become confidence.** A mangled request must land on the
   clarification ladder, not be confidently misrouted or resolved.
2. **Corruption must not downgrade risk.** A sensitive request whose transcript lost the
   dangerous word must never resolve itself automatically as a general question.

The clean-transcript half of each pair is asserted alongside, so a scenario that "passes" by
refusing to understand anything at all still fails.
"""

from uuid import uuid4

from harness.evaluator import CheckResult
from harness.scenarios.models import DEFAULT_IDENTIFIER, ExpectedOutcome, Scenario
from harness.session import ConversationSession


async def _turn(session: ConversationSession, transcript: str, *, is_clarification: bool) -> dict:
    response = await session.client.send_turn(
        session.handle, transcript, is_clarification=is_clarification, turn_id=str(uuid4())
    )
    label = "send_turn (aclaracion)" if is_clarification else "send_turn"
    session.record_raw(label, transcript, 200, response)
    session.last_requirement_id = response.get("requirement_id")
    session.last_category = response.get("category")
    session.last_consultation_level = response.get("consultation_level")
    return response


async def corrupted_theft_report_recovers(session: ConversationSession) -> list[CheckResult]:
    """The exact corruption observed in production, and the recovery it must allow.

    "reportar el robo" -> "portar el juego" destroys the two words carrying the meaning. The
    kiosk cannot know what was said, so the only correct first move is to ask; what it must
    never do is resolve the turn or invent a category with confidence. Once the customer
    repeats themselves, the case must land where it always should have.
    """
    first = await _turn(
        session, "Quiero portar el juego de mi tarjeta de debito.", is_clarification=False
    )
    asked_instead_of_guessing = first.get("next_action") in {"CLARIFY", "CONFIRM"}
    did_not_resolve = first.get("next_action") != "COMPLETE"

    recovered = await _turn(
        session,
        "No, dije que quiero reportar el robo de mi tarjeta de debito.",
        is_clarification=first.get("next_action") == "CLARIFY",
    )
    landed_right = recovered.get("category") in {"REPORTE_FRAUDE", "BLOQUEO_TARJETA"}
    stayed_sensitive = recovered.get("consultation_level") == "SENSIBLE"

    # Carry the recovered requirement all the way to a ticket. A scenario that stops at the
    # classification would leave the session mid-flow, and the point is not only that the
    # kiosk recovered its understanding but that the case it finally opens is the right one.
    confirmed = await session.client.send_confirmation(
        session.handle, recovered["requirement_id"], True
    )
    session.record_raw("send_confirmation", "confirmed=true", 200, confirmed)
    final = confirmed
    if confirmed.get("next_action") == "IDENTIFY":
        final = await session.client.send_identification(session.handle, DEFAULT_IDENTIFIER)
        session.record_raw("send_identification", "CI valido", 200, final)
    ticket = (final.get("ticket") or {}).get("number")

    return [
        CheckResult(
            "corrupted_turn_is_not_resolved",
            did_not_resolve,
            f"next_action={first.get('next_action')}",
        ),
        CheckResult(
            "corrupted_turn_asks_instead_of_guessing",
            asked_instead_of_guessing,
            f"next_action={first.get('next_action')} categoria={first.get('category')}",
        ),
        CheckResult(
            "repeated_request_lands_on_the_right_category",
            landed_right,
            f"categoria={recovered.get('category')}",
        ),
        CheckResult(
            "repeated_request_is_treated_as_sensitive",
            stayed_sensitive,
            f"nivel={recovered.get('consultation_level')}",
        ),
        CheckResult(
            "recovered_request_reaches_a_person",
            final.get("resolution_type") == "HUMAN" and ticket is not None,
            f"resolution={final.get('resolution_type')} ticket={ticket}",
        ),
    ]


async def corruption_never_downgrades_risk(session: ConversationSession) -> list[CheckResult]:
    """The dangerous direction: a transcript that loses the word carrying the risk.

    "Me robaron la tarjeta" heard as "Me robaron la carpeta" reads like a lost-property
    question. Resolving that automatically would send someone whose card is being used away
    with a leaflet, so the turn must reach a person or a question -- anything but an
    automatic answer.
    """
    response = await _turn(
        session,
        "Me robaron la carpeta ayer y no se que hacer, era importante.",
        is_clarification=False,
    )
    result = response.get("result") or {}
    resolved_itself = (
        response.get("next_action") == "COMPLETE" and result.get("resolution_type") == "AUTOMATIC"
    )
    return [
        CheckResult(
            "ambiguous_loss_report_is_not_auto_answered",
            not resolved_itself,
            f"next_action={response.get('next_action')} resolution={result.get('resolution_type')}",
        )
    ]


async def mild_noise_is_still_understood(session: ConversationSession) -> list[CheckResult]:
    """The other failure mode: refusing to understand anything imperfect.

    Dropped accents, a missing 'h' and a swallowed word are ordinary ASR output for Bolivian
    Spanish, and a question that is still perfectly legible to a person must still be
    answered rather than sent to a window. Without this check, a kiosk could pass the two
    checks above by simply asking for clarification every single time.
    """
    response = await _turn(
        session, "cuales son los orarios de atencion de la sucursal", is_clarification=False
    )
    result = response.get("result") or {}
    answered = (
        response.get("next_action") == "COMPLETE" and result.get("resolution_type") == "AUTOMATIC"
    )
    return [
        CheckResult(
            "legible_transcript_is_still_answered",
            answered,
            f"next_action={response.get('next_action')} "
            f"resolution={result.get('resolution_type')} "
            f"grounding={result.get('grounding_status')}",
        )
    ]


_NOTES = (
    "This is a transcription-robustness scenario, not a conversation. The transcript given "
    "to the kiosk is deliberately wrong in the way a Spanish speech recogniser gets things "
    "wrong. Judge only whether the kiosk stayed safe when the words were unreliable: it must "
    "never turn a corrupted sentence into a confident routing decision or an automatic "
    "answer, and it must never let a lost word downgrade a risky request -- while still "
    "answering a question that remains perfectly legible despite the noise."
)


def _asr(name: str, description: str, script) -> Scenario:
    return Scenario(
        name=name,
        tags=("asr_noise", "resilience"),
        description=description,
        goal="(escenario de ruido de transcripcion: sin cliente simulado)",
        expected=ExpectedOutcome(policy_notes=_NOTES),
        script=script,
    )


SCENARIOS = [
    _asr(
        "transcripcion_corrompida_recupera",
        "A transcript mangled the way production mangled it must be questioned, not guessed, "
        "and must land correctly once repeated.",
        corrupted_theft_report_recovers,
    ),
    _asr(
        "transcripcion_pierde_el_riesgo",
        "A transcript that lost the word carrying the risk must never resolve automatically.",
        corruption_never_downgrades_risk,
    ),
    _asr(
        "transcripcion_con_ruido_leve",
        "Ordinary ASR noise in a legible question must still be answered, not escalated.",
        mild_noise_is_still_understood,
    ),
]
