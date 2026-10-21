"""Naturalness rules for customer-facing text.

The classifier writes `customer_summary` and the grounder writes the answer; both are
read aloud to someone standing at a kiosk. These regexes reject the registers that
break that illusion -- third-person reference to the person being spoken to, and
usted-form address -- and `customer_summary_for` supplies the fallback wording when a
summary is rejected.

Leaf module: imports nothing from the application except enums.
"""

import re

from app.domain.enums import Category

_CUSTOMER_SUMMARIES = {
    Category.BLOQUEO_TARJETA: "Necesitas bloquear una tarjeta.",
    Category.REPORTE_FRAUDE: (
        "Necesitas reportar un posible fraude o un movimiento no reconocido."
    ),
    Category.CONSULTA_GENERAL: "Necesitas orientación sobre una consulta bancaria.",
    Category.SOLICITUD_CREDITO: ("Quieres información o ayuda con una solicitud de crédito."),
    Category.BANCA_DIGITAL: "Necesitas ayuda con la banca digital.",
}
_UNNATURAL_CUSTOMER_LANGUAGE = re.compile(
    r"\busuario\b|\b(?:el|la|un|una)\s+(?:cliente|persona)\b|"
    r"\b(?:usted|su|sus)\b|"
    r"\b(?:puede|podría|podria|indique|ingrese|describa|dígame|digame|"
    r"confirme|cuénteme|cuenteme|responda|escriba|necesita)\b",
    re.IGNORECASE,
)
_NATURAL_SUMMARY_OPENING = re.compile(
    r"^(?:necesitas|quieres|buscas|deseas|solicitas|reportas|tienes|te\b|"
    r"no\s+reconoces|notaste|identificaste)",
    re.IGNORECASE,
)
# A customer_summary that restates the clarification instead of the need: `decirme`,
# `contarme`, `indicarme` and `falta saber` all mark the kiosk still asking rather than
# summarising something it understood.
_SUMMARY_IS_A_QUESTION = re.compile(
    r"\b(?:decirme|contarme|indicarme|precisarme|aclararme|falta\s+saber|"
    r"especificar(?:me)?)\b",
    re.IGNORECASE,
)
# Narrower than _UNNATURAL_CUSTOMER_LANGUAGE: a multi-sentence RAG answer legitimately uses
# "puede", "necesita" or "su" to talk about the bank or the product ("el banco puede pedir tu
# documento"), so only third-person references to the person asking, and usted-form address,
# disqualify it. The usted imperatives are the ones with no other reading -- nobody tells the
# bank to "recuerde" -- and they are what the grounder copies from a corpus written in usted
# ("Recuerde presentar primero el reclamo", "confirme antes de venir", 2026-10-20).
_UNNATURAL_THIRD_PERSON_REFERENCE = re.compile(
    r"\busuario\b|\b(?:el|la|un|una)\s+(?:cliente|persona)\b|\b(?:usted|ustedes)\b|"
    r"\b(?:recuerde|acuda|ac[eé]rquese|dir[ií]jase|comun[ií]quese|confirme|consulte|"
    r"verifique|conserve|solicite|ll[aá]menos|tenga\s+en\s+cuenta)\b",
    re.IGNORECASE,
)


def customer_summary_for(category: Category) -> str:
    return _CUSTOMER_SUMMARIES[category]


def customer_facing_text_is_natural(text: str) -> bool:
    return not _UNNATURAL_CUSTOMER_LANGUAGE.search(text)


# The person at the kiosk does not know a corpus exists, so an answer that cites "la
# evidencia" reads like an internal note ("La evidencia documenta...", 2026-10-21).
_CORPUS_REFERENCE = re.compile(
    r"\b(?:la|esta|seg[uú]n\s+la)\s+evidencia\b|\bseg[uú]n\s+lo\s+publicado\b|"
    r"\b(?:los|estos)\s+documentos\s+(?:indican|se[nñ]alan|documentan|dicen|mencionan)\b",
    re.IGNORECASE,
)


def grounded_answer_is_natural(text: str) -> bool:
    return not (_UNNATURAL_THIRD_PERSON_REFERENCE.search(text) or _CORPUS_REFERENCE.search(text))


# A customer_summary reading back a further need: "...y también saber a qué hora abre". The
# classification prompt asks the summary to enumerate every need it returns, so this next to
# an empty additional_needs is the decision contradicting itself.
_ENUMERATED_NEED = re.compile(
    r"\s+(?:y|e)\s*,?\s*(?:luego|despu[eé]s|aparte|adem[aá]s|tambi[eé]n)\b", re.IGNORECASE
)


def summary_lists_an_unreturned_need(customer_summary: str, additional_needs: int) -> bool:
    return additional_needs == 0 and bool(_ENUMERATED_NEED.search(customer_summary))


def clarification_is_simple(text: str | None) -> bool:
    """A comprehension retry must be one short question about one concept."""
    if not text:
        return False
    words = re.findall(r"\b[\wáéíóúüñ]+\b", text, re.IGNORECASE)
    return (
        1 <= len(words) <= 12
        and text.count("?") <= 1
        and not re.search(r"[,;:]|\b(?:o|u)\b", text, re.IGNORECASE)
    )


def clarification_is_materially_simpler(candidate: str | None, previous: str | None) -> bool:
    """Whether a repair question is both usable and meaningfully different.

    Comprehension is not a word-count contest. A concrete explanation can be longer than an
    opaque two-word question, so length is deliberately not compared here. The one-concept
    constraint and lexical difference prevent option lists and verbatim repeats.
    """
    if not clarification_is_simple(candidate):
        return False
    if not previous:
        return True
    normalized_candidate = " ".join(re.findall(r"\w+", candidate.casefold()))
    normalized_previous = " ".join(re.findall(r"\w+", previous.casefold()))
    if normalized_candidate == normalized_previous:
        return False
    return True


_COMPREHENSION_REPAIR_QUESTIONS = {
    Category.BLOQUEO_TARJETA: ("¿Quieres que tu tarjeta deje de funcionar para que nadie la use?"),
    Category.REPORTE_FRAUDE: "¿Viste un cobro que tú no hiciste?",
    Category.BANCA_DIGITAL: "¿No puedes entrar a la banca digital?",
    Category.SOLICITUD_CREDITO: "¿Necesitas ayuda con un crédito que ya pediste?",
    Category.CONSULTA_GENERAL: "¿Qué necesitas hacer en el banco?",
}


def comprehension_repair_question(
    category: Category,
    candidate: str | None,
    previous: str | None,
) -> str:
    """Choose a concrete one-concept repair after the customer says they did not understand.

    The model's candidate is kept when it satisfies the repair contract. Otherwise the
    category policy supplies a stable accessible fallback. These are domain-level prompts,
    not scenario phrases, and live here so the graph contains no wording branches.
    """
    if clarification_is_materially_simpler(candidate, previous):
        return candidate
    fallback = _COMPREHENSION_REPAIR_QUESTIONS[category]
    if clarification_is_materially_simpler(fallback, previous):
        return fallback
    # The category fallback can only equal the prior question after it has already been used.
    # Returning it lets the ordinary clarification budget route to a human on that turn; the
    # graph never emits it a second time.
    return fallback


def unresolved_customer_summary(category: Category) -> str:
    """Describe the established topic without inventing the requested action."""
    topics = {
        Category.BLOQUEO_TARJETA: "Tienes un problema con una tarjeta",
        Category.REPORTE_FRAUDE: "Tienes un posible problema de seguridad bancaria",
        Category.BANCA_DIGITAL: "Tienes un problema relacionado con la banca digital",
        Category.SOLICITUD_CREDITO: "Necesitas ayuda con un tema de crédito",
        Category.CONSULTA_GENERAL: "Necesitas ayuda con una consulta bancaria",
    }
    return f"{topics[category]}, pero no pudimos precisar qué ayuda necesitas."
