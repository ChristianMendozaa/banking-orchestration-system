from harness.client import SessionHandle
from harness.evaluator import CheckResult
from harness.personas import PERSONAS
from harness.session import ConversationSession


def test_every_persona_has_a_non_empty_goal() -> None:
    for persona in PERSONAS:
        assert persona.name
        assert len(persona.goal) > 10


def test_persona_names_are_unique() -> None:
    names = [persona.name for persona in PERSONAS]
    assert len(names) == len(set(names))


def test_every_persona_expectation_checks_run_without_error() -> None:
    session = ConversationSession(client=None, handle=SessionHandle("sid", "tok"))
    for persona in PERSONAS:
        checks = persona.expectation_checks(session, {})
        assert isinstance(checks, list)
        assert all(isinstance(check, CheckResult) for check in checks)


def test_default_persona_has_no_expectation_checks() -> None:
    from harness.personas import Persona

    persona = Persona(name="sin_expectativas", goal="algo generico")
    session = ConversationSession(client=None, handle=SessionHandle("sid", "tok"))
    assert persona.expectation_checks(session, {}) == []
