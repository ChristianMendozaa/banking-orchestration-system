"""Turn a written answer into something worth listening to.

Grounded answers come back as prose for a screen: markdown bullets, bold, blank lines. Read
aloud verbatim that becomes "guion ser mayor de dieciocho anos" and a list with no audible
structure. The written form is what the customer reads on screen and what gets stored; this
is only what is handed to the speech model.
"""

import re

from app.core.text import strip_internal_identifiers

_BULLET = re.compile(r"^[\s]*[-*•]\s+", re.MULTILINE)
_ORDERED = re.compile(r"^[\s]*\d+[.)]\s+", re.MULTILINE)
_HEADING = re.compile(r"^[\s]*#{1,6}\s*", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*\*|__|\*|_|`)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BLANK_LINES = re.compile(r"\n{2,}")


def for_speech(text: str) -> str:
    """Flatten markdown into one spoken paragraph.

    Each list item becomes its own sentence, so the pauses a reader gets from the line
    breaks survive as pauses a listener gets from the punctuation.
    """
    if not text:
        return text

    # Already applied where a grounded answer is built, so this is belt and braces -- but it
    # is the last gate before audio, and a UUID that gets past it is not a confusing line on
    # a screen, it is half a minute of spoken hexadecimal the customer has to sit through.
    spoken = strip_internal_identifiers(text)
    spoken = _LINK.sub(r"\1", spoken)
    spoken = _HEADING.sub("", spoken)
    spoken = _BULLET.sub("", spoken)
    spoken = _ORDERED.sub("", spoken)
    spoken = _EMPHASIS.sub("", spoken)

    lines = [line.strip() for line in _BLANK_LINES.sub("\n", spoken).split("\n")]
    sentences = []
    for line in lines:
        if not line:
            continue
        # A line that already ends in punctuation keeps it; one that does not -- which is
        # every bullet -- gets a full stop, because that is the pause it had on screen.
        sentences.append(line if line[-1] in ".:;!?" else f"{line}.")

    # A colon introduces the list that follows it, so it must not also end the sentence.
    joined = " ".join(sentences).replace(": ", ": ").replace(".:", ":")
    return re.sub(r"\s+", " ", joined).strip()
