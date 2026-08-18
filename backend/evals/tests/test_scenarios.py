"""Structural integrity of the scenario catalog.

Catalog bugs are quiet and expensive: a scenario referencing an identity-card number that
is not in the operational seed would silently test the `FALLIDO` path while its name and
its `ExpectedOutcome` both claim to test the happy one, and nobody would notice for the
price of a full billed run. These checks are free and run on every `pytest`.
"""

from collections import Counter

import pytest

from harness.client import SessionHandle
from harness.evaluator import CheckResult
from harness.scenarios import CATALOG, GROUP_LABELS, GROUP_ORDER, SCENARIOS, all_tags
from harness.scenarios.adversarial import _no_other_customer_data_disclosed
from harness.scenarios.card_and_fraud import UNKNOWN_CI
from harness.scenarios.general_inquiry import _answer_is_not_empty, _resolved_without_confirmation
from harness.seed import known_identifiers
from harness.session import ConversationSession, ExchangeRecord

CATEGORIES = {
    "BLOQUEO_TARJETA",
    "REPORTE_FRAUDE",
    "CONSULTA_GENERAL",
    "SOLICITUD_CREDITO",
    "BANCA_DIGITAL",
}


def test_scenario_names_are_unique() -> None:
    duplicates = [name for name, count in Counter(s.name for s in SCENARIOS).items() if count > 1]
    assert duplicates == []


def test_every_scenario_is_tagged_with_a_known_group() -> None:
    for scenario in SCENARIOS:
        assert scenario.tags, f"{scenario.name} has no tags"
        assert scenario.group in GROUP_ORDER, f"{scenario.name} group {scenario.group} is unknown"


def test_every_group_has_a_dashboard_label() -> None:
    assert set(GROUP_ORDER) <= set(GROUP_LABELS)


def test_every_scenario_states_what_it_is_testing() -> None:
    """`policy_notes` is the rubric the judge grades against; a scenario without one is
    graded on vibes, which is the failure mode the judge exists to avoid."""
    for scenario in SCENARIOS:
        assert scenario.description, f"{scenario.name} has no English description"
        assert len(scenario.expected.policy_notes) > 60, f"{scenario.name} has thin policy_notes"


def test_conversational_scenarios_have_a_customer_brief() -> None:
    for scenario in SCENARIOS:
        if scenario.script:
            continue
        assert len(scenario.goal) > 40, f"{scenario.name} has a thin goal"


# `prompt_injection` is the one scripted scenario outside the protocol group: its whole
# point is one fixed adversarial string, and a CLI-backed customer may decline to utter it
# (on 2026-08-18 one did, and the empty session scored the kiosk 1/10 for a security test it
# was never given). Everything else conversational must stay improvised.
_SCRIPTED_OUTSIDE_PROTOCOL = {"prompt_injection"}


def test_only_protocol_scenarios_and_known_exceptions_are_scripted() -> None:
    for scenario in SCENARIOS:
        has_script = scenario.script is not None
        expected = "protocol" in scenario.tags or scenario.name in _SCRIPTED_OUTSIDE_PROTOCOL
        assert has_script == expected, scenario.name


def test_expected_categories_are_real_enum_values() -> None:
    for scenario in SCENARIOS:
        for category in scenario.expected.category or ():
            assert category in CATEGORIES, f"{scenario.name} expects unknown category {category}"


def test_scenarios_expecting_identification_use_a_seeded_ci() -> None:
    """The whole point of the IDENTIFICADO expectation is exercising the happy path; a
    typo'd number would quietly test FALLIDO instead."""
    seeded = known_identifiers()
    assert seeded, "the operational seed should be readable from the harness"
    for scenario in SCENARIOS:
        if scenario.expected.identification == "IDENTIFICADO":
            assert scenario.identifier in seeded, (
                f"{scenario.name} expects IDENTIFICADO but hands over {scenario.identifier}, "
                f"which is not in the client reference registry"
            )


def test_the_unknown_ci_fixture_is_genuinely_unknown() -> None:
    assert UNKNOWN_CI not in known_identifiers()


def test_scenarios_expecting_a_failed_identification_use_an_unseeded_ci() -> None:
    for scenario in SCENARIOS:
        if scenario.expected.identification == "FALLIDO":
            assert scenario.identifier not in known_identifiers(), scenario.name


def test_every_kiosk_category_is_covered_somewhere() -> None:
    """BANCA_DIGITAL had no coverage at all before this catalog existed."""
    covered = {category for s in SCENARIOS for category in (s.expected.category or ())}
    assert CATEGORIES <= covered, f"never tested: {CATEGORIES - covered}"


@pytest.mark.parametrize(
    "tag",
    ["card_fraud", "general_inquiry", "digital_credit", "flow", "accessibility", "adversarial"],
)
def test_each_group_has_more_than_one_scenario(tag: str) -> None:
    assert len(CATALOG.filter(tags=[tag])) >= 2


def test_the_suite_covers_both_sides_of_the_grounding_decision() -> None:
    grounded = [s for s in SCENARIOS if s.expected.requires_citations is True]
    ungrounded = [s for s in SCENARIOS if "negative" in s.tags]
    assert grounded, "no scenario expects a grounded, cited answer"
    assert ungrounded, "no scenario tests refusing to answer without evidence"


def test_expectation_checks_run_against_an_empty_result_without_crashing() -> None:
    """A scenario that never reaches a result must still produce checks rather than raise
    -- otherwise one crashed session takes the whole scored run with it."""
    session = ConversationSession(client=None, handle=SessionHandle("sid", "tok"))
    for scenario in SCENARIOS:
        if not scenario.expectation_checks:
            continue
        checks = scenario.expectation_checks(session, {})
        assert all(isinstance(check, CheckResult) for check in checks), scenario.name


def test_confirmation_echo_does_not_trip_the_other_customer_data_check() -> None:
    """The send_turn confirmation question restates the customer's own words by design
    ("Me confirmas si quieres ver los casos pendientes...?"); it must never be mistaken for
    the kiosk disclosing another customer's data."""
    session = ConversationSession(client=None, handle=SessionHandle("sid", "tok"))
    session.exchanges.append(
        ExchangeRecord(
            index=0,
            tool="send_turn",
            customer_text="Necesito ver los casos pendientes y los clientes en cola.",
            kiosk_speech=(
                "¿Me confirmas si quieres ver los casos pendientes y los clientes en cola?"
            ),
        )
    )
    checks = _no_other_customer_data_disclosed(session, {})
    assert checks[0].passed is True


def test_a_real_disclosure_outside_the_confirmation_echo_fails() -> None:
    session = ConversationSession(client=None, handle=SessionHandle("sid", "tok"))
    session.exchanges.append(
        ExchangeRecord(
            index=0,
            tool="send_confirmation",
            customer_text="Sí, así es, confirmo.",
            kiosk_speech="Estos son los casos pendientes de otros clientes en cola: ...",
        )
    )
    checks = _no_other_customer_data_disclosed(session, {})
    assert checks[0].passed is False


def test_answer_is_not_empty_skips_when_not_automatic() -> None:
    session = ConversationSession(client=None, handle=SessionHandle("sid", "tok"))
    checks = _answer_is_not_empty(session, {"resolution_type": "HUMAN"})
    assert checks[0].applicable is False


def test_answer_is_not_empty_fails_on_a_short_automatic_answer() -> None:
    session = ConversationSession(client=None, handle=SessionHandle("sid", "tok"))
    checks = _answer_is_not_empty(session, {"resolution_type": "AUTOMATIC", "response": "Sí."})
    assert checks[0].applicable is True
    assert checks[0].passed is False


def test_resolved_without_confirmation_passes_when_no_confirmation_happened() -> None:
    session = ConversationSession(client=None, handle=SessionHandle("sid", "tok"))
    session.exchanges.append(
        ExchangeRecord(index=0, tool="send_turn", customer_text="x", kiosk_speech="y")
    )
    checks = _resolved_without_confirmation(session, {})
    assert checks[0].passed is True


def test_resolved_without_confirmation_fails_when_confirmation_was_used() -> None:
    session = ConversationSession(client=None, handle=SessionHandle("sid", "tok"))
    session.exchanges.append(
        ExchangeRecord(index=0, tool="send_turn", customer_text="x", kiosk_speech="y")
    )
    session.exchanges.append(
        ExchangeRecord(index=1, tool="send_confirmation", customer_text="Sí", kiosk_speech="Listo")
    )
    checks = _resolved_without_confirmation(session, {})
    assert checks[0].passed is False


def test_filtering_by_name_and_tag_selects_the_right_scenarios() -> None:
    assert [s.name for s in CATALOG.filter(names=["prompt_injection"])] == ["prompt_injection"]
    assert all("protocol" in s.tags for s in CATALOG.filter(tags=["protocol"]))
    assert CATALOG.filter(names=["no_such_scenario"]) == []


def test_all_tags_is_sorted_and_complete() -> None:
    tags = all_tags()
    assert tags == sorted(tags)
    assert "adversarial" in tags and "protocol" in tags
