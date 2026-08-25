"""Normalization shared by corpus indexing and lexical retrieval."""

import re
import unicodedata


def normalize_search_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9ñ]+", without_marks))
