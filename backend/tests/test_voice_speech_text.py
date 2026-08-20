"""What the kiosk says out loud, versus what it puts on screen."""

import pytest

from app.core.text import strip_internal_identifiers
from app.services.voice.speech_text import for_speech


def test_a_bulleted_answer_becomes_sentences() -> None:
    """Read verbatim, "- Ser mayor" is spoken as the word "guion". Each item is a sentence."""
    spoken = for_speech(
        "Para sacar un crédito te piden:\n\n"
        "- Ser mayor de 18 años.\n"
        "- Las últimas tres boletas de pago.\n"
    )
    assert spoken == (
        "Para sacar un crédito te piden: Ser mayor de 18 años. Las últimas tres boletas de pago."
    )
    assert "-" not in spoken


def test_an_unpunctuated_item_gains_the_pause_it_had_on_screen() -> None:
    assert for_speech("- Documento vigente\n- Boletas de pago") == (
        "Documento vigente. Boletas de pago."
    )


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        ("**Importante**: trae tu CI.", "Importante: trae tu CI."),
        ("## Requisitos\nTrae tu CI.", "Requisitos. Trae tu CI."),
        ("1. Primero esto.\n2. Luego lo otro.", "Primero esto. Luego lo otro."),
        ("Consulta [la guía](https://x.test).", "Consulta la guía."),
    ],
)
def test_markdown_never_reaches_the_speaker(written: str, spoken: str) -> None:
    assert for_speech(written) == spoken


def test_ordinary_prose_is_left_alone() -> None:
    # Most answers are already one sentence. Rewriting those would only risk changing them.
    plain = "La Sucursal Centro atiende de lunes a viernes de 08:30 a 19:00."
    assert for_speech(plain) == plain
    assert for_speech("") == ""


def test_internal_chunk_ids_never_reach_the_customer() -> None:
    """A live answer once ended with "ID de respaldo: ce4c11e2-..." -- a knowledge_chunks
    primary key the model copied out of its own evidence blocks. On screen that is a
    confusing trailing line; read aloud it is thirty-two characters of hexadecimal."""
    from app.core.text import strip_internal_identifiers

    assert (
        strip_internal_identifiers(
            "Para sacar un crédito te piden:\n- Ser mayor de 18 años.\n\n"
            "ID de respaldo: ce4c11e2-c3ae-4eba-ae9e-da30f676c588"
        )
        == "Para sacar un crédito te piden:\n- Ser mayor de 18 años."
    )


def test_stripping_an_identifier_keeps_the_sentence_around_it() -> None:
    assert (
        strip_internal_identifiers("Respuesta normal. (ref 11111111-2222-3333-4444-555555555555)")
        == "Respuesta normal."
    )
    # A colon and digits in ordinary prose must survive -- opening hours look a lot like a
    # labelled value to a regex that is not anchored carefully.
    plain = "Horario 08:30 a 19:00 en la agencia Centro: consulta ahí."
    assert strip_internal_identifiers(plain) == plain
