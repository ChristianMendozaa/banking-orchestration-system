"""Everything the kiosk says, and the plans that tell the voice model how to say it.

A `SpeechPlan` is not a script. It carries `facts` (data the model may reword),
`verbatim` (strings that must survive word for word), `guidance` (what to do with them)
and `fallback_text` (the written rendering, for the text channel -- never read aloud).

What belongs in `verbatim` and what belongs in `facts`: `verbatim` is checked by the
client against what was actually spoken, so it can only hold strings that survive that
comparison as text -- the grounded answer, the credential warning, an executive's name,
a window label. Numbers cannot go in it. A model that says "tu ticket es el cuarenta y
dos" has done nothing wrong, and a substring check on "42" would flag it and force a
pointless re-read. The ticket number and the wait estimate therefore travel in `facts`
with guidance to state them exactly, and the ticket screen stays the authoritative copy
of both.

This module is pure: it takes values and returns `SpeechPlan`s. It touches no session,
no database and no agent.
"""

from app.domain.enums import Category
from app.domain.schemas import ExecutiveAssignment, SpeechPlan

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

# What belongs in `verbatim` and what belongs in `facts`.
#
# `verbatim` is checked by the client against what was actually spoken, so it can only hold
# strings that survive that comparison as text: the grounded answer, the credential warning,
# an executive's name, a window label. Numbers cannot go in it -- a model that says "tu
# ticket es el cuarenta y dos" has done nothing wrong, and a substring check on "42" would
# flag it and force a pointless re-read. The ticket number and the wait estimate therefore
# travel in `facts` with guidance to state them exactly, and the ticket screen stays the
# authoritative copy of both.


# Split so the warning half can travel in `verbatim` on its own: the instruction to use the
# protected field is a fact the model may reword, the prohibition is not.
IDENTIFICATION_WARNING = "No escribas contraseñas, PIN ni datos financieros."
IDENTIFICATION_SPEECH_TEXT = (
    f"Para continuar, escribe tu CI en el campo protegido. {IDENTIFICATION_WARNING}"
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
            "alta. Luego deja de hacer preguntas mientras escribe."
        ),
        fallback_text=IDENTIFICATION_SPEECH_TEXT,
    )


def answer_plan(final_response: str | None) -> tuple[str, SpeechPlan]:
    """A question the corpus answered. Returns the written rendering and the plan."""
    speech = final_response or "Tu consulta quedó resuelta."
    return speech, SpeechPlan(
        intent="ANSWER",
        # The answer is bound to the retrieved evidence and was already checked
        # against it (`GroundedAnswerDecision.supported`). Rewording it would break
        # that binding, so it is the one long string the model must reproduce.
        verbatim=[speech],
        guidance=(
            "Entrega la respuesta de `verbatim` tal cual, completa y sin resumirla "
            "ni agregarle datos. Puedes presentarla y cerrarla con tus palabras. "
            "Después pregúntale si necesita algo más y sigue escuchando."
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
) -> tuple[str, SpeechPlan]:
    """A named executive at a named window. Returns the written rendering and the plan."""
    reason = HANDOFF_REASONS.get(category, "")
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
        verbatim=[assignment.window_number, assignment.name],
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
