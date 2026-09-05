"""Reading a spoken reply to a confirmation question, deterministically where possible.

This decision used to live in the browser, as one regular expression over the transcript,
and reached the backend as a single boolean (`ConfirmationRequest.confirmed`). Three things
were wrong with that. The backend could not audit what the person actually said; folding
diacritics collapsed the affirmation "sí" onto the conditional "si", so "si no es correcto,
corrígelo" confirmed a banking requirement that sentence was questioning; and a reply that
is neither yes nor no -- a question, a correction, a yes with a new concern attached -- had
nowhere to go.

The cue tables stay because they are right about the easy cases and they are free: a plain
"sí" must not cost a model round trip in the middle of a conversation. Everything they
cannot settle goes to the model (`OpenAIProvider.read_confirmation`), and the backend --
never the client -- decides what happens next.
"""

import re
import unicodedata

# Without a bare "si": the accent is the whole distinction between the affirmation and the
# conditional conjunction, and folding removes it.
_POSITIVE = re.compile(
    r"\b(sip|correcto|correcta|confirmo|confirmar|de acuerdo|esta bien|es correcto|"
    r"es correcta|claro|exacto|exactamente|asi es|asi mismo|eso es|por supuesto|obvio|"
    r"dale|afirmativo|ya pues)\b"
)
_NEGATIVE = re.compile(
    r"\b(no|incorrecto|incorrecta|corregir|correccion|cambiar|equivocado|equivocada|"
    r"negativo|tampoco|para nada|nada que ver|mas bien)\b"
)
_ADVERSATIVE = re.compile(r"\b(pero|aunque|sin embargo|en realidad|mejor dicho|espera)\b")
# `\b` is ASCII-only in Python's `re` for these purposes too, so the edges are spelled out.
_ACCENTED_YES = re.compile(r"(?<![^\W\d_])sí(?![^\W\d_])", re.UNICODE)
_BARE_YES = re.compile(r"^(?:si|sip)$")


def fold(value: str) -> str:
    compacted = " ".join(value.split()).casefold()
    decomposed = unicodedata.normalize("NFD", compacted)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


# A reply the cue tables may settle on their own. "Sí", "no, es incorrecto" and "así es"
# carry nothing but the answer; past that, the extra words are usually the interesting part
# -- "no, quería consultar los requisitos" is a rejection that already said what it wanted
# instead, and settling it here would throw that away and make the person say it again.
MAX_SETTLED_WORDS = 4


def unambiguous_confirmation(transcript: str) -> bool | None:
    """True, False, or None when the reply needs reading rather than matching.

    None is not a failure and must never be spent as a correction: it is the signal that a
    model has to look at the sentence.
    """
    spoken = " ".join(transcript.split()).casefold()
    normalized = fold(transcript)
    if not normalized:
        return None
    # Someone who answers a yes/no question with a question of their own has not answered
    # it. "Claro, ¿qué entendiste?" matched `claro` and confirmed the requirement.
    if "?" in spoken or "¿" in spoken:
        return None
    # "Sí, pero quiero consultar primero" is a yes to a different question. An adversative
    # connector means the sentence qualifies whatever cue precedes it, and a cue table
    # cannot tell how -- so nothing here is settled once one appears.
    if _ADVERSATIVE.search(normalized):
        return None
    if len(normalized.split()) > MAX_SETTLED_WORDS:
        return None

    accented = _ACCENTED_YES.search(spoken)
    yes = accented is not None or _BARE_YES.match(normalized) is not None
    negative = _NEGATIVE.search(normalized) is not None
    positive_match = _POSITIVE.search(normalized)
    positive = yes or positive_match is not None

    if positive != negative:
        return positive
    # Either neither cue fired, or both did: "sí, y además no reconozco un cargo" is a yes
    # carrying a second, unrelated concern that must not be swallowed by the yes. Both are
    # exactly the shapes the model has to look at.
    return None
