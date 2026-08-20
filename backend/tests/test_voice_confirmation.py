"""Reading a spoken yes or no.

These cases moved here with the parser itself, from the browser tests that covered it while
it lived in `frontend/lib/kiosk-realtime.ts`. They are Bolivian Spanish, not textbook
Spanish, because that is what the kiosk hears.
"""

import pytest

from app.services.voice.confirmation import explicit_confirmation


@pytest.mark.parametrize(
    "spoken",
    ["si", "Sí", "claro", "así es", "exacto", "por supuesto", "dale", "ya pues", "correcto"],
)
def test_natural_bolivian_yes_is_a_yes(spoken: str) -> None:
    assert explicit_confirmation(spoken) is True


@pytest.mark.parametrize(
    "spoken",
    ["no", "para nada", "nada que ver", "incorrecto", "quiero corregir", "está equivocado"],
)
def test_natural_bolivian_no_is_a_no(spoken: str) -> None:
    assert explicit_confirmation(spoken) is False


def test_no_se_is_read_as_a_rejection() -> None:
    """Ported behaviour, kept deliberately.

    "No sé" is not really a correction, but reading it as one sends the customer back to
    describing the case -- and after `max_corrections` of those, to a person. That is the
    right direction to fail in, so this is not treated as ambiguous.
    """
    assert explicit_confirmation("no sé") is False


@pytest.mark.parametrize("spoken", ["mmm", "espera", "sí, pero no", "sí pero espera"])
def test_ambiguous_answers_are_not_read_as_either(spoken: str) -> None:
    """None is the kiosk re-asking, not the kiosk failing.

    Guessing here opens or drops a case on a sentence nobody unambiguously said.
    """
    assert explicit_confirmation(spoken) is None


def test_a_yes_followed_by_more_detail_is_still_a_yes() -> None:
    # No adversative connector: the customer confirmed and then kept talking. Re-asking here
    # is the kiosk failing to hear a yes it was given.
    assert explicit_confirmation("Sí, y además no reconozco un cargo") is True


def test_a_retraction_is_not_a_yes() -> None:
    assert explicit_confirmation("Sí, pero no, mejor dicho no era eso") is None


def test_a_qualified_yes_is_not_a_yes() -> None:
    """Stricter than the browser parser this replaced, and the reason is the architecture.

    That parser cross-checked the realtime model's own `confirmed` boolean, so a half-read
    yes needed two independent mistakes to open a case. This one runs alone.
    """
    assert explicit_confirmation("sí pero espera") is None
    assert explicit_confirmation("sí, en realidad era otra cosa") is None
    # Still unqualified, so still a yes.
    assert explicit_confirmation("sí, y además no reconozco un cargo") is True
