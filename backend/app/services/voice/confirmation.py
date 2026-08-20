"""Read a spoken yes or no the way Bolivian Spanish actually says it.

This used to live in the browser (`frontend/lib/kiosk-realtime.ts::explicitConfirmation`),
where it existed to second-guess the realtime model's `confirmed` boolean. There is no
model to second-guess any more -- the transcript goes straight from the recogniser to here
-- but the reading itself is the same problem and the same answer, so it moved rather than
disappeared.
"""

import re
import unicodedata

# "Si" is the least of it. Every one of these is an ordinary confirmation at a counter in
# La Paz, and every one of them used to fall through to ASK_EXPLICIT_CONFIRMATION -- so the
# kiosk re-asked a question it had already been answered, which reads as not listening.
POSITIVE = re.compile(
    r"\b(si|sip|correcto|correcta|confirmo|confirmar|de acuerdo|esta bien|es correcto|"
    r"es correcta|claro|exacto|exactamente|asi es|asi mismo|eso es|por supuesto|obvio|"
    r"dale|afirmativo|ya pues)\b"
)
NEGATIVE = re.compile(
    r"\b(no|incorrecto|incorrecta|corregir|correccion|cambiar|equivocado|equivocada|"
    r"negativo|tampoco|para nada|nada que ver|mas bien)\b"
)
ADVERSATIVE = re.compile(r"\b(pero|aunque|sin embargo|en realidad|mejor dicho|espera)\b")


def normalize(value: str) -> str:
    folded = unicodedata.normalize("NFD", " ".join(value.split()).casefold())
    return "".join(char for char in folded if not unicodedata.combining(char))


def explicit_confirmation(value: str) -> bool | None:
    """True for yes, False for no, None when the answer is not unambiguous.

    None is not a failure mode -- it is the kiosk declining to open or drop a case on a
    sentence it cannot read, and the caller re-asks.
    """
    normalized = normalize(value)
    positive = POSITIVE.search(normalized)
    negative = NEGATIVE.search(normalized)
    adversative = ADVERSATIVE.search(normalized)

    # A yes that is immediately qualified -- "si pero espera", "si, en realidad no era eso"
    # -- is not a yes yet. This is stricter than the browser version this parser was ported
    # from, and deliberately so: that version was the second of two gates, cross-checked
    # against the realtime model's own `confirmed` boolean. There is no model and no second
    # gate any more, so this reading is the only thing standing between a half-answer and an
    # opened case. The asymmetry is intentional -- a misread yes opens a case the customer
    # did not ask for, while a misread no only re-asks.
    if positive is not None and adversative is not None and adversative.start() > positive.start():
        return None

    if bool(positive) != bool(negative):
        return positive is not None
    if positive is None:
        return None

    # Both cues are present and nothing qualified the yes. "Si, y ademas no reconozco un
    # cargo" is a confirmation followed by more detail, and whichever cue came first is the
    # answer -- re-asking there is the kiosk failing to hear a yes it was given.
    if positive.start() == negative.start():
        return None
    return positive.start() < negative.start()
