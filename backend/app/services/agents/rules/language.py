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
# disqualify it.
_UNNATURAL_THIRD_PERSON_REFERENCE = re.compile(
    r"\busuario\b|\b(?:el|la|un|una)\s+(?:cliente|persona)\b|\b(?:usted|ustedes)\b",
    re.IGNORECASE,
)


def customer_summary_for(category: Category) -> str:
    return _CUSTOMER_SUMMARIES[category]


def customer_facing_text_is_natural(text: str) -> bool:
    return not _UNNATURAL_CUSTOMER_LANGUAGE.search(text)


def grounded_answer_is_natural(text: str) -> bool:
    return not _UNNATURAL_THIRD_PERSON_REFERENCE.search(text)
