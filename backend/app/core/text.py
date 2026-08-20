"""Text the customer is allowed to see or hear."""

import re

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# The observed shape: a whole line that is nothing but a label and an id. Anchored to the
# line so it cannot reach backwards into the sentence before it.
_IDENTIFIER_LINE = re.compile(
    rf"^[^\n:]{{0,60}}:[ \t]*{_UUID}[ \t]*$", re.IGNORECASE | re.MULTILINE
)
# Anything left over: a bare id mid-sentence. Removing just the id keeps the sentence.
_BARE_IDENTIFIER = re.compile(rf"\s*\b{_UUID}\b", re.IGNORECASE)
_EMPTY_PARENS = re.compile(r"\(\s*[^()]{0,12}\s*\)")


def strip_internal_identifiers(text: str) -> str:
    """Remove any internal UUID that leaked into customer-facing text.

    Evidence reaches the grounding model inside <evidence id="..."> blocks, and the model has
    been observed copying one of those ids into its answer -- a live kiosk answer ended with
    "ID de respaldo: ce4c11e2-...", which is a knowledge_chunks primary key. The prompt
    already forbids describing where an answer came from; this is the part that does not
    depend on the model complying.

    No legitimate banking answer contains a UUID, so they go wherever they appear -- but only
    the identifier and the label introducing it, never the sentence around them.
    """
    cleaned = _IDENTIFIER_LINE.sub("", text)
    if _BARE_IDENTIFIER.search(cleaned):
        cleaned = _BARE_IDENTIFIER.sub("", cleaned)
        cleaned = _EMPTY_PARENS.sub("", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()
