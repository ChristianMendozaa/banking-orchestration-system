"""The simulated customer's wiring.

Does not call `agent.run()` -- that needs a real key and costs money. The fake key in
`conftest` only satisfies the client's construction-time credential check.
"""

from conftest import make_scenario

from harness.agent import build_customer_agent, build_system_message
from harness.client import KioskClient, SessionHandle
from harness.model_client import build_model_client, is_known_to_autogen, resolve_provider
from harness.scenarios import SCENARIOS
from harness.scenarios.models import ANGUSTIADO
from harness.session import ConversationSession


def _session() -> ConversationSession:
    return ConversationSession(KioskClient("http://fake"), SessionHandle("sid", "tok"))


def test_agent_binds_exactly_the_three_kiosk_tools() -> None:
    agent = build_customer_agent(
        model_client=build_model_client("gpt-5.4-mini"), session=_session(), scenario=SCENARIOS[0]
    )
    assert agent.name == "cliente_simulado"
    assert {tool.name for tool in agent._tools} == {
        "send_turn",
        "send_confirmation",
        "send_identification",
    }


def test_system_message_combines_the_situation_and_the_speaking_style() -> None:
    """Goal and style are separate fields precisely so the same situation can be re-tested
    through a different mouth -- both have to reach the prompt."""
    scenario = make_scenario(goal="Te robaron la tarjeta.", style=ANGUSTIADO)
    message = build_system_message(scenario)
    assert "Te robaron la tarjeta." in message
    assert ANGUSTIADO.instruction in message


def test_a_scenario_with_an_identifier_tells_the_customer_which_ci_to_give() -> None:
    message = build_system_message(make_scenario(identifier="6735666"))
    assert "6735666" in message


def test_a_scenario_without_an_identifier_forbids_inventing_one() -> None:
    message = build_system_message(make_scenario(identifier=None))
    assert "inventar" in message


def test_a_customer_without_a_ci_is_not_told_to_answer_with_a_turn() -> None:
    """The state machine rejects a turn while the session is AWAITING_IDENTIFICATION, so
    telling the persona to explain itself that way manufactures a 409 the kiosk is not
    responsible for -- which is exactly what an earlier version of this prompt did."""
    message = build_system_message(make_scenario(identifier=None))
    no_ci_clause = message.split("No tienes ningun documento")[1].split("\n")[0]
    assert "send_turn" not in no_ci_clause
    assert "TERMINATE" in message


def test_the_persona_is_told_to_follow_next_action_to_the_end() -> None:
    """gpt-5.4-mini otherwise stops after one turn in some scenarios, leaving the session
    stranded at AWAITING_CONFIRMATION and scoring the kiosk for the harness's shortfall."""
    message = build_system_message(make_scenario())
    for action in ("CLARIFY", "CONFIRM", "IDENTIFY", "COMPLETE"):
        assert action in message
    assert "No dejes" in message


def test_an_unrecognised_model_name_still_builds_a_client() -> None:
    """`autogen-ext` rejects model names missing from the table baked into the pinned
    release, which would break the harness on any model newer than that release."""
    assert is_known_to_autogen("definitely-not-a-real-model-name") is False
    client = build_model_client("definitely-not-a-real-model-name")
    assert client.model_info["structured_output"] is True
    assert client.model_info["function_calling"] is True


# --- provider resolution (--model / --judge-model sentinels) ------------------------


def test_an_ordinary_model_name_resolves_to_no_provider() -> None:
    """Every model name that predates the CLI backends must keep going through
    build_model_client() -- resolve_provider() is additive, not a new required step."""
    assert resolve_provider("gpt-5.4-mini") == (None, None)


def test_a_bare_cli_sentinel_resolves_to_that_providers_own_default_model() -> None:
    assert resolve_provider("claude-code") == ("claude-code", None)
    assert resolve_provider("codex") == ("codex", None)


def test_a_colon_suffixed_sentinel_carries_the_underlying_model() -> None:
    assert resolve_provider("claude-code:opus") == ("claude-code", "opus")
    assert resolve_provider("codex:gpt-5.2-codex") == ("codex", "gpt-5.2-codex")


def test_a_model_name_that_merely_contains_a_provider_word_is_not_a_sentinel() -> None:
    """Only an exact "claude-code"/"codex" prefix before the colon counts -- a real model
    name that happens to start with one must not be silently routed to the CLI path."""
    assert resolve_provider("codex-mini-latest") == (None, None)
