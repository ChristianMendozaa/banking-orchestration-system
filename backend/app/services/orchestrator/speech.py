"""Everything the kiosk says, and the plans that tell the voice model how to say it.

A `SpeechPlan` is not a script. It carries `facts` (data the model may reword),
`verbatim` (strings that must survive word for word), `guidance` (what to do with them)
and `fallback_text` (the written rendering, for the text channel -- never read aloud).

What belongs in `verbatim` and what belongs in `facts`: `verbatim` is checked by the
client against what was actually spoken, so it can only be *measured* on strings that
survive that comparison as text -- the credential warning, an executive's name. Anything
carrying a digit cannot: a model that says "tu ticket es el cuarenta y dos" has done
nothing wrong, and a substring check on "42" would flag a correct reading. The client
therefore skips digit-bearing entries outright (`missingVerbatim`), and this module keeps
them out in the first place: the ticket number, the wait estimate and the window label
travel in `facts` with guidance to state them exactly, and the ticket screen stays the
authoritative copy. The grounded answer used to be the one long digit-bearing entry here;
since 2026-09-05 `verbatim` carries only its short spoken rendering (see `answer_plan`),
which is both what a kiosk should say out loud and something the client's check can
actually settle.

This module is pure: it takes values and returns `SpeechPlan`s. It touches no session,
no database and no agent.
"""

from app.domain.enums import Category, ResolutionType
from app.domain.schemas import ExecutiveAssignment, FlowOutcome, SpeechPlan

# The written rendering of a declined turn, used by the text channel and as the voice
# channel's `fallback_text`. The voice channel no longer reads it aloud: it gets
# `decline_plan()` below and words the refusal itself.
DECLINE_SPEECH_TEXT = (
    "En este kiosco solo puedo ayudarte con bloqueo de tarjetas, reporte de fraude, "
    "solicitudes de crédito, banca digital y consultas generales del banco. Para eso no te "
    "puedo ayudar aquí; si necesitas otra cosa, acércate con un ejecutivo en la sucursal."
)

# One short, deterministic reason per category, said before the ticket/desk/wait sentence in
# a human handoff -- so a person does not just hear a ticket number with no explanation of
# why they are being sent to a person. Kept separate from _CUSTOMER_SUMMARIES in agents.py:
# that one describes the customer's need in the confirmation step, this one frames the
# handoff itself.
HANDOFF_REASONS = {
    Category.BLOQUEO_TARJETA: "Voy a derivarte con un ejecutivo para bloquear tu tarjeta.",
    Category.REPORTE_FRAUDE: (
        "Voy a derivarte con un ejecutivo de prevención de fraude para atender tu reporte."
    ),
    Category.CONSULTA_GENERAL: "Voy a derivarte con un ejecutivo para atender tu consulta.",
    Category.SOLICITUD_CREDITO: (
        "Voy a derivarte con un ejecutivo de créditos para continuar tu trámite."
    ),
    Category.BANCA_DIGITAL: (
        "Voy a derivarte con un ejecutivo de banca digital para resolver tu caso."
    ),
}
URGENT_HANDOFF_REASSURANCE = " Este caso se está atendiendo como prioritario."


# The services the kiosk can actually attend. Named as a fact rather than a fixed sentence
# so the model can decline in its own words -- but it may not add to this list, which is why
# it is passed as data and repeated in the guidance.
KIOSK_SCOPE = (
    "bloqueo de tarjetas, reporte de fraude, solicitudes de crédito, banca digital y "
    "consultas generales del banco"
)

# What belongs in `verbatim` and what belongs in `facts` -- see the module docstring. The
# short version: operational tokens that carry a digit (ticket number, wait estimate,
# window label) go in `facts`, because the client's text comparison cannot settle them.


# Split so the warning half can travel in `verbatim` on its own: the instruction to use the
# protected field is a fact the model may reword, the prohibition is not.
IDENTIFICATION_WARNING = "No escribas contraseñas, PIN ni datos financieros."
IDENTIFICATION_SPEECH_TEXT = (
    f"Para continuar, escribe tu CI en el campo protegido. {IDENTIFICATION_WARNING}"
)

VOICE_PRIVACY_NOTICE = (
    "Por seguridad, no digas números de tarjeta ni datos financieros en voz alta."
)
_VOICE_FINANCIAL_PII = {"TARJETA", "MONTO", "CUENTA"}


def with_privacy_notice(
    speech: str,
    plan: SpeechPlan,
    pii_types: list[str],
) -> tuple[str, SpeechPlan]:
    """Prepend immediate voice-safety guidance when this turn contained financial PII."""
    if not _VOICE_FINANCIAL_PII.intersection(pii_types):
        return speech, plan
    warned_speech = f"{VOICE_PRIVACY_NOTICE} {speech}"
    return warned_speech, plan.model_copy(
        update={
            "verbatim": list(dict.fromkeys([VOICE_PRIVACY_NOTICE, *plan.verbatim])),
            "guidance": (
                "Primero repite la advertencia de `verbatim` sobre datos en voz alta. "
                f"Después sigue esta instrucción: {plan.guidance}"
            ),
            "fallback_text": warned_speech,
        }
    )


def decline_plan() -> SpeechPlan:
    return SpeechPlan(
        intent="DECLINE",
        facts={"alcance": KIOSK_SCOPE},
        guidance=(
            "Dile con amabilidad que eso no lo puedes atender en este kiosco y nómbrale lo "
            "que sí atiendes, tomándolo de `alcance`. No ofrezcas ningún servicio que no "
            "esté en esa lista, no pidas confirmación y no sigas la conversación."
        ),
        fallback_text=DECLINE_SPEECH_TEXT,
    )


def clarify_plan(question: str) -> SpeechPlan:
    return SpeechPlan(
        intent="CLARIFY",
        facts={"pregunta": question},
        guidance=(
            "Haz esa pregunta con tus palabras, en una sola frase breve y cordial. No "
            "preguntes nada más y no supongas la respuesta."
        ),
        fallback_text=question,
    )


def confirm_plan(customer_summary: str, fallback_text: str) -> SpeechPlan:
    return SpeechPlan(
        intent="CONFIRM",
        facts={"entendido": customer_summary},
        guidance=(
            "Confirma en una pregunta breve y natural que entendiste eso. No agregues "
            "detalles que no estén en `entendido` y espera un sí o un no antes de seguir."
        ),
        fallback_text=fallback_text,
    )


def reconfirm_plan(customer_summary: str, *, asked_a_question: bool) -> tuple[str, SpeechPlan]:
    """The reply was neither a yes nor a no, so nothing has moved.

    Two shapes, one state. Someone who asked what the kiosk understood gets the summary
    explained; someone whose answer could not be read gets asked again plainly. Neither
    spends a correction, and neither advances the flow -- which is the whole point: the
    browser used to answer "no quedó claro" by re-asking, and answer a question with a yes.
    """
    speech = (
        f"Entendí esto: {customer_summary}"
        if asked_a_question
        else f"¿Me confirmas que {customer_summary[0].lower()}{customer_summary[1:]}?"
        if customer_summary
        else "¿Me lo confirmas?"
    )
    guidance = (
        "Explícale con tus palabras lo que entendiste, tomándolo de `entendido`, y espera "
        "a que te diga si es correcto. No agregues nada que no esté ahí y no des el "
        "trámite por confirmado."
        if asked_a_question
        else "No quedó claro si te dijo que sí o que no. Vuelve a preguntárselo con tus "
        "palabras, apoyándote en `entendido`, y pídele una respuesta clara."
    )
    return speech, SpeechPlan(
        intent="CONFIRM",
        facts={"entendido": customer_summary},
        guidance=guidance,
        fallback_text=speech,
    )


HANDOFF_CONFIRMATION_TEXT = (
    "No pude precisar exactamente qué necesitas. ¿Quieres que te atienda una persona?"
)


def handoff_confirmation_plan() -> SpeechPlan:
    return SpeechPlan(
        intent="CONFIRM",
        facts={"accion": "recibir ayuda de una persona"},
        guidance=(
            "Explica brevemente que no pudiste precisar la necesidad y pregunta solamente "
            "si quiere que una persona la atienda. No menciones una acción bancaria concreta."
        ),
        fallback_text=HANDOFF_CONFIRMATION_TEXT,
    )


CAPTURE_SPEECH_TEXT = "Cuéntame nuevamente qué necesitas."


def capture_plan() -> SpeechPlan:
    """The summary was rejected and the kiosk is asking for the need again."""
    return SpeechPlan(
        intent="CAPTURE",
        guidance=(
            "No entendiste bien lo que necesitaba. Pídele que te lo cuente otra "
            "vez, con calma y sin disculparte de más. No repitas el resumen que "
            "acaba de rechazar."
        ),
        fallback_text="Cuéntame nuevamente qué necesitas.",
    )


def identification_plan() -> SpeechPlan:
    """A protected-field CI entry. The warning is `verbatim`; the instruction is a fact."""
    return SpeechPlan(
        intent="IDENTIFY",
        facts={"accion": "escribir su CI en el campo protegido de la pantalla"},
        verbatim=[IDENTIFICATION_WARNING],
        guidance=(
            "Pídele que haga lo que dice `accion` y repite la advertencia de "
            "`verbatim` palabra por palabra. Nunca le pidas que dicte el CI en voz "
            "alta. Después cállate: no hagas ninguna pregunta, ni siquiera si está "
            "lista o si quiere seguir. Espera en silencio a que termine de escribir."
        ),
        fallback_text=IDENTIFICATION_SPEECH_TEXT,
    )


def answer_plan(
    final_response: str | None,
    *,
    spoken_response: str | None = None,
    conversation_can_continue: bool = True,
) -> tuple[str, SpeechPlan]:
    """A question the corpus answered. Returns the written rendering and the plan.

    Two renderings of one answer. `final_response` is the full grounded text -- it goes on
    screen, into the case record and into `fallback_text` for the text channel.
    `spoken_response` is the one- or two-sentence version the same grounding call produced,
    and it is the only one the voice model is asked to keep intact.

    Forcing the full answer through `verbatim` made a conversational model read a paragraph
    aloud, and made the client's verbatim check fail on every reasonable rendering of it.
    Shortening it here rather than letting the model summarise keeps the spoken words bound
    to the evidence they were checked against (`GroundedAnswerDecision.supported`).
    """
    speech = final_response or "Tu consulta quedó resuelta."
    spoken = (spoken_response or "").strip() or speech
    return speech, SpeechPlan(
        intent="ANSWER",
        # Put the approved answer in `facts` as well as `verbatim`. The compact Realtime
        # model reliably treats `facts` as tool data, while `verbatim` preserves the exact
        # grounded wording. Keeping both prevents it from claiming that the tool supplied
        # no hours or requirements even though the approved answer was present.
        facts={"respuesta_fundamentada": spoken},
        verbatim=[spoken],
        guidance=(
            "Di la respuesta de `verbatim` tal cual, sin alargarla ni agregarle datos. "
            "Es corta a propósito: no la amplíes. "
            + (
                "Después pregúntale si necesita algo más y sigue escuchando."
                if conversation_can_continue
                else (
                    "Explícale brevemente que esta atención llegó a su límite y despídete; "
                    "no hagas otra pregunta."
                )
            )
        ),
        fallback_text=speech,
    )


def handoff_plan(
    *,
    category: Category,
    ticket_number: int,
    estimated_wait_minutes: int | None,
    assignment: ExecutiveAssignment,
    urgent_case: bool,
    unresolved_summary: str | None = None,
) -> tuple[str, SpeechPlan]:
    """A named executive at a named window. Returns the written rendering and the plan."""
    reason = (
        f"Voy a derivarte con un ejecutivo para ayudarte. {unresolved_summary}"
        if unresolved_summary
        else HANDOFF_REASONS.get(category, "")
    )
    urgent = URGENT_HANDOFF_REASSURANCE if urgent_case else ""
    wait_message = (
        f" La espera estimada es de {estimated_wait_minutes} minutos."
        if estimated_wait_minutes is not None
        else ""
    )
    speech = (
        f"{reason}{urgent} Tu ticket es {ticket_number}. Dirígete a "
        f"{assignment.window_number} con {assignment.name}.{wait_message}"
    )
    facts = {
        "motivo": reason,
        "ticket": str(ticket_number),
        "ventanilla": assignment.window_number,
        "ejecutivo": assignment.name,
    }
    if estimated_wait_minutes is not None:
        facts["espera_minutos"] = str(estimated_wait_minutes)
    if urgent_case:
        facts["prioritario"] = "sí"
    return speech, SpeechPlan(
        intent="HANDOFF",
        facts=facts,
        # The window travels in `facts` only: the seed calls it "Ventanilla 3", and a model
        # that says "ventanilla tres" is right while the substring check is not.
        verbatim=[assignment.name],
        guidance=(
            "Explícale con tus palabras por qué lo derivas, usando `motivo`, y "
            "dale el número de ticket, la ventanilla y el nombre del ejecutivo "
            "exactamente como aparecen en `facts`. Si hay `espera_minutos`, "
            "menciónalo. Si hay `prioritario`, dile que su caso se atiende como "
            "prioritario. Despídete: a partir de aquí lo atiende una persona."
        ),
        fallback_text=speech,
    )


def pending_assignment_plan(ticket_number: int) -> tuple[str, SpeechPlan]:
    """A ticket with no window behind it yet. Never invent one."""
    speech = f"Tu ticket es {ticket_number}. La asignación está pendiente."
    return speech, SpeechPlan(
        intent="HANDOFF",
        facts={"ticket": str(ticket_number), "asignacion": "pendiente"},
        guidance=(
            "Dale el número de ticket exactamente como aparece y explícale que "
            "todavía no hay una ventanilla asignada, que espere a que lo llamen. "
            "No inventes un ejecutivo ni una ventanilla."
        ),
        fallback_text=speech,
    )


def compose_outcomes_plan(
    primary_speech: str,
    primary_plan: SpeechPlan,
    outcomes: list[FlowOutcome],
) -> tuple[str, SpeechPlan]:
    """Compose independent case outcomes without putting language in response shaping."""
    if len(outcomes) <= 1:
        return primary_speech, primary_plan

    additions: list[str] = []
    verbatim = list(primary_plan.verbatim)
    for outcome in outcomes[1:]:
        need = outcome.customer_summary.rstrip(".")
        for opening in ("necesitas ", "quieres "):
            if need.casefold().startswith(opening):
                need = need[len(opening) :]
                break
        if outcome.resolution_type is ResolutionType.AUTOMATIC:
            # Same rule as `answer_plan`: what gets said is the short rendering, what gets
            # shown is the full one. A composed narrative that pastes several full grounded
            # answers together is the longest thing the kiosk can possibly say.
            spoken = (outcome.grounding_detail or {}).get("spoken") or outcome.response
            additions.append(f"Sobre {need}: {spoken}")
        elif outcome.executive and outcome.ticket:
            additions.append(
                f"Sobre {need}, tu ticket es {outcome.ticket.number}. Dirígete a "
                f"{outcome.executive.window_number} con {outcome.executive.name}."
            )
            # Only the name is verifiable as spoken text; the ticket number and the window
            # carry digits and stay in the composed narrative and on the ticket screen.
            verbatim.append(outcome.executive.name)
        elif outcome.ticket:
            additions.append(
                f"Sobre {need}, conserva también el ticket {outcome.ticket.number}; "
                "está pendiente de asignación."
            )
        else:  # Defensive: a human outcome is not actionable until it owns a ticket.
            continue

    speech = " ".join([primary_speech, *additions])
    return speech, SpeechPlan(
        intent=(
            "HANDOFF"
            if any(outcome.resolution_type is ResolutionType.HUMAN for outcome in outcomes)
            else "ANSWER"
        ),
        facts={"resultados": speech},
        verbatim=list(dict.fromkeys(verbatim)),
        guidance=(
            "Comunica cada resultado y número de ticket; no omitas ninguna necesidad "
            "independiente y no combines sus destinos."
        ),
        fallback_text=speech,
    )
