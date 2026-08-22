"""The deterministic consultation-level floor.

`consultation_level` is load-bearing three times over -- it decides whether the kiosk
confirms (`turn_nodes.requires_confirmation`), whether the case is ANONIMO or PENDIENTE
(`confirmation_nodes.create_case_for_requirement`) and whether the answer may come from
RAG (`InitialAttentionAgent.run`) -- so a single intermittent GENERAL from the model
costs identification and human escalation in one HTTP request.

The floor only ever raises the model's answer, never lowers it. Read this together with
`app.services.prompts.classification`, which is the model-facing half of the same rule.

Leaf module: imports nothing from the application except enums.
"""

import re

from app.domain.enums import Category, ConsultationLevel

_LEVEL_ORDER = {
    ConsultationLevel.GENERAL: 0,
    ConsultationLevel.PERSONALIZADA: 1,
    ConsultationLevel.SENSIBLE: 2,
}

# Something already happened to this person's own money or plastic. These phrasings are not
# ambiguous in Bolivian Spanish and they survive the hypothetical guard below: "me robaron"
# is never preventive.
_INCIDENT_EVENT = re.compile(
    r"me\s+robaron|robaron\s+mi|me\s+clonaron|clonaron\s+(?:mi|la)|me\s+sacaron|"
    r"no\s+reconozco|no\s+reconoc[ií]|no\s+autoric[eé]|"
    r"me\s+(?:aparec|sali)\w*\s+(?:un|dos|tres|varios)?\s*"
    r"(?:cargo|cobro|consumo|movimiento|consumos|cargos)|"
    r"se\s+trag[oó]\s+mi\s+tarjeta|me\s+(?:la|lo)\s+(?:usaron|vaciaron)|"
    r"perd[ií]\s+mi\b|se\s+me\s+perdi[oó]|extravi[eé]",
    re.IGNORECASE,
)
# Weaker than _INCIDENT_EVENT: naming one's own banking object is enough to make a request
# personal, but a preventive question can mention the same objects, so the hypothetical guard
# can veto these.
_OWN_BANKING_OBJECT = re.compile(
    r"\bmi\s+tarjeta\b|\bmis?\s+cuentas?\b|\bmis\s+movimientos\b|\bmi\s+saldo\b|"
    r"\bmi\s+plata\b|\bmi\s+dinero\b",
    re.IGNORECASE,
)
# Own file / own access, with no incident and no money moving: PERSONALIZADA territory.
_OWN_FILE_OR_ACCESS = re.compile(
    r"no\s+puedo\s+(?:acceder|entrar|ingresar)|no\s+logro\s+(?:entrar|ingresar|acceder)|"
    r"\bmi\s+(?:contraseña|contrasena|clave|usuario|app|aplicaci[oó]n|extracto|"
    r"solicitud|cr[eé]dito|pr[eé]stamo|tr[aá]mite)\b|"
    r"estado\s+de\s+mi\b|c[oó]mo\s+va\s+mi\b",
    re.IGNORECASE,
)
# A digital-banking request that reports an operation of one's own failing. Named separately
# because these phrasings carry no possessive at all ("hice tres intentos de transferencia y
# las tres veces fallo") and would otherwise read as a product question.
_DIGITAL_OPERATION_FAILURE = re.compile(
    r"fall[oó]|fallaron|no\s+me\s+deja|no\s+funciona|me\s+rechaz|rechazad|"
    r"\bintentos?\b|\berror\b|bloquead",
    re.IGNORECASE,
)
# Preventive or hypothetical framing. Vetoes _OWN_BANKING_OBJECT and the digital-failure rule,
# never _INCIDENT_EVENT.
_HYPOTHETICAL = re.compile(
    r"si\s+alg[uú]n\s+d[ií]a|por\s+si\s+acaso|por\s+si\s+alguna\s+vez|por\s+prevenci[oó]n|"
    r"en\s+caso\s+de\s+que|no\s+me\s+pas[oó]\s+nada|todav[ií]a\s+no|hipot[eé]tic|"
    r"a[uú]n\s+no\s+soy\s+cliente|no\s+es\s+(?:un\s+)?caso\s+real",
    re.IGNORECASE,
)


# A negator immediately before an incident phrase reverses it: "no me robaron nada" and "ni me
# robaron" are someone stating that nothing happened, and `_INCIDENT_EVENT` deliberately
# outranks the hypothetical guard, so without this a preventive question that says so plainly
# was read as a theft report. The `\s+` matters: "No, me robaron la tarjeta" -- a comma, an
# answer to a question rather than a negation -- must still count as an incident.
_NEGATED_INCIDENT = re.compile(
    r"\b(?:no|nunca|jam[aá]s|tampoco|ni)\s+(?:me\s+|se\s+me\s+)?$",
    re.IGNORECASE,
)


def _reports_an_incident(masked_text: str) -> bool:
    """True when the text describes an incident that is not being denied."""
    return any(
        not _NEGATED_INCIDENT.search(masked_text[max(0, match.start() - 40) : match.start()])
        for match in _INCIDENT_EVENT.finditer(masked_text)
    )


def sensitivity_floor(masked_text: str, category: Category) -> ConsultationLevel | None:
    """The lowest consultation level this request may be treated as, from its text alone.
    `None` means the text carries no signal and the classifier's own answer stands.

    This exists because `consultation_level` is load-bearing three times over -- it decides
    whether the kiosk confirms (`turn_nodes.requires_confirmation`), whether the case is
    ANONIMO or PENDIENTE (`confirmation_nodes.create_case_for_requirement`) and whether the
    answer comes from RAG (`InitialAttentionAgent.run`) -- so a single intermittent GENERAL
    from the model costs identification and human escalation in one HTTP request. The floor
    only ever raises: the model stays in charge of everything it is better at.
    """
    if category is Category.REPORTE_FRAUDE:
        # A fraud report is, by definition, about this person's own money. A purely
        # informational question about fraud classifies as CONSULTA_GENERAL instead.
        return ConsultationLevel.SENSIBLE
    if _reports_an_incident(masked_text):
        return ConsultationLevel.SENSIBLE
    preventive = bool(_HYPOTHETICAL.search(masked_text))
    if not preventive and _OWN_BANKING_OBJECT.search(masked_text):
        return ConsultationLevel.SENSIBLE
    if _OWN_FILE_OR_ACCESS.search(masked_text):
        return ConsultationLevel.PERSONALIZADA
    if (
        not preventive
        and category is Category.BANCA_DIGITAL
        and _DIGITAL_OPERATION_FAILURE.search(masked_text)
    ):
        return ConsultationLevel.PERSONALIZADA
    return None
