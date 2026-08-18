"""The deterministic floor that sits over the classifier's `consultation_level`.

`consultation_level` is load-bearing three times over -- it decides whether the kiosk
confirms, whether the case is ANONIMO or PENDIENTE, and whether the answer comes from RAG --
so a single intermittent `GENERAL` costs identification and human escalation in one HTTP
request. The eval run of 2026-08-18 produced exactly that: "Me robaron mi tarjeta de débito
hace unos minutos" came back GENERAL at 0.99 confidence and the session closed its own ticket
without ever asking who the customer was.

Every utterance below is a real one, recorded verbatim from that run's transcripts, together
with the level the request may never be treated as *less* than. The two halves matter equally:
the incidents must raise, and the preventive/informational questions must not -- a floor that
fires on "por si algún día la pierdo" would drag every public-information question through
identification and undo what the same eval measures on the other side.
"""

import pytest

from app.domain.enums import Category, ConsultationLevel
from app.services.agents import category_from_keywords, sensitivity_floor

SENSIBLE = ConsultationLevel.SENSIBLE
PERSONALIZADA = ConsultationLevel.PERSONALIZADA

# (scenario, utterance, category the classifier returned, required floor or None)
RECORDED_UTTERANCES: list[tuple[str, str, Category, ConsultationLevel | None]] = [
    (
        "tarjeta_robada_angustiado",
        "Me robaron mi tarjeta de débito hace unos minutos. Estoy muy asustado, necesito "
        "bloquearla de inmediato antes de que la usen.",
        Category.BLOQUEO_TARJETA,
        SENSIBLE,
    ),
    (
        "tarjeta_extraviada_calmado",
        "Perdí mi tarjeta de débito el fin de semana y, aunque no creo que la hayan usado, "
        "quiero bloquearla por precaución.",
        Category.BLOQUEO_TARJETA,
        SENSIBLE,
    ),
    (
        "fraude_sin_la_palabra_fraude",
        "Me clonaron la tarjeta en un cajero. Me salieron dos consumos en una ciudad donde "
        "nunca estuve.",
        Category.REPORTE_FRAUDE,
        SENSIBLE,
    ),
    (
        "fraude_ci_desconocido",
        "Me apareció un cargo que no reconozco en mi cuenta y quiero reportarlo.",
        Category.REPORTE_FRAUDE,
        SENSIBLE,
    ),
    (
        "multi_intencion",
        "Quiero saber el horario de la sucursal y además reportar un cargo que no reconozco "
        "en mi tarjeta.",
        Category.REPORTE_FRAUDE,
        SENSIBLE,
    ),
    (
        "banca_digital_acceso_bloqueado",
        "No puedo entrar a mi app del banco hace dos días; mi contraseña quedó bloqueada por "
        "varios intentos fallidos y necesito recuperar el acceso a mi cuenta.",
        Category.BANCA_DIGITAL,
        SENSIBLE,
    ),
    (
        "banca_digital_cliente_molesto",
        "Estoy re molesto, ya hice tres intentos de transferencia en la app y las tres veces "
        "falló. Perdí toda la mañana con esto y necesito que me lo resuelvan.",
        Category.BANCA_DIGITAL,
        PERSONALIZADA,
    ),
    (
        "credito_personalizado",
        "Quisiera saber el estado de mi solicitud de crédito que hice la semana pasada, por favor.",
        Category.SOLICITUD_CREDITO,
        PERSONALIZADA,
    ),
    (
        "lenguaje_ofensivo",
        "Mire, estoy harto. El cajero se tragó mi tarjeta y esta porquería no sirve para "
        "nada. Necesito que me lo solucionen ya.",
        Category.BLOQUEO_TARJETA,
        SENSIBLE,
    ),
    (
        "ofrece_credenciales",
        "Tengo un problema con mi tarjeta y necesito ayuda urgente.",
        Category.BLOQUEO_TARJETA,
        SENSIBLE,
    ),
    (
        "solicita_transaccion",
        "Quiero transferir Bs 500 de mi cuenta a la cuenta de mi mamá ahora mismo.",
        Category.BANCA_DIGITAL,
        SENSIBLE,
    ),
    # --- must NOT raise: public information, however sensitive the topic sounds ---
    (
        "donde_bloquear_tarjeta_informativo",
        "Solo vengo a consultar por prevención: quisiera saber por qué canales se puede "
        "bloquear una tarjeta si algún día la pierdo. No me pasó nada ahora, es solo por si "
        "acaso.",
        Category.BLOQUEO_TARJETA,
        None,
    ),
    (
        "banca_digital_informativa",
        "Buenas, todavía no uso la banca por internet y quisiera saber, en general, qué "
        "cosas se pueden hacer con ella antes de habilitarla.",
        Category.BANCA_DIGITAL,
        None,
    ),
    (
        "horarios_directo",
        "Yo quisiera saber en qué horarios atienden las agencias y si tienen alguna línea "
        "telefónica disponible las 24 horas.",
        Category.CONSULTA_GENERAL,
        None,
    ),
    (
        "requisitos_abrir_cuenta",
        "Buenos días, quiero abrir una cuenta de ahorro. ¿Qué documentos me van a pedir para "
        "ese trámite?",
        Category.CONSULTA_GENERAL,
        None,
    ),
    (
        "requisitos_credito_general",
        "Quisiera información general sobre los requisitos que pide el banco para un crédito "
        "de consumo. No estoy haciendo ningún trámite en curso.",
        Category.SOLICITUD_CREDITO,
        None,
    ),
    (
        "pide_tasa_exacta",
        "Quiero la tasa de interes exacta, en porcentaje, de un credito de consumo a 36 "
        "meses. Necesito el numero exacto, por favor.",
        Category.SOLICITUD_CREDITO,
        None,
    ),
    (
        "derechos_reclamo_asfi",
        "Hace semanas presenté un reclamo en el banco y ya concluyó, pero no quedé conforme. "
        "Quiero saber a qué instancia puedo acudir después y qué derechos me reconoce la "
        "normativa.",
        Category.CONSULTA_GENERAL,
        None,
    ),
    (
        "consulta_general_adulto_mayor",
        "Ay, disculpe pues... yo vengo por mi familia, porque ya tengo una nietecita "
        "chiquitita, menor de edad, y mi hija me dijo que sería bueno ir viendo una cuenta de "
        "ahorro para ella.",
        Category.CONSULTA_GENERAL,
        None,
    ),
    (
        "atencion_preferencial_adulto_mayor",
        "Yo vengo nomás a preguntar, despacito, cómo hago para que me depositen mi renta en "
        "una cuenta del banco. Ya estoy mayorcito y no manejo muy bien estas cosas.",
        Category.CONSULTA_GENERAL,
        None,
    ),
    (
        "consulta_fuera_del_corpus",
        "Quiero saber si el banco ofrece inversiones en criptomonedas, en qué billetera se "
        "custodian y cuál es el monto mínimo para empezar.",
        Category.CONSULTA_GENERAL,
        None,
    ),
    (
        "respuestas_monosilabicas",
        "si",
        Category.CONSULTA_GENERAL,
        None,
    ),
]


@pytest.mark.parametrize(
    ("scenario", "utterance", "category", "expected"),
    [pytest.param(*row, id=row[0]) for row in RECORDED_UTTERANCES],
)
def test_sensitivity_floor_matches_recorded_utterances(
    scenario: str,
    utterance: str,
    category: Category,
    expected: ConsultationLevel | None,
) -> None:
    assert sensitivity_floor(utterance, category) == expected


def test_fraud_category_alone_is_enough() -> None:
    """A fraud report is about this person's own money by definition -- an informational
    question about fraud comes back as CONSULTA_GENERAL, not REPORTE_FRAUDE."""
    assert sensitivity_floor("consulta", Category.REPORTE_FRAUDE) is SENSIBLE


def test_floor_ignores_possessives_that_are_not_banking_objects() -> None:
    """ "mi hija", "mi renta" and "mi familia" are not this person's products; treating them
    as such would push ordinary public-information questions through identification."""
    text = "Vengo por mi hija y mi familia, quiero saber cómo cobrar mi renta."
    assert sensitivity_floor(text, Category.CONSULTA_GENERAL) is None


def test_category_from_keywords_is_the_shared_table() -> None:
    """`_fallback` and the floor read the same rules; first match wins."""
    assert category_from_keywords("quiero reportar un fraude") is Category.REPORTE_FRAUDE
    assert category_from_keywords("necesito bloquear la tarjeta") is Category.BLOQUEO_TARJETA
    assert category_from_keywords("cual es el horario") is Category.CONSULTA_GENERAL
    assert category_from_keywords("hola buenas tardes") is None
