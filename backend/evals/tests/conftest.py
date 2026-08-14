"""Shared fixtures.

Every test here is hermetic: no network, no OpenAI key, no running backend. The live
run (`python -m harness`) is the behavioural verification; this suite verifies the wiring,
the scoring rules and the renderers.
"""

import pytest

from harness.client import SessionHandle
from harness.evaluator import CheckResult
from harness.judge import DimensionScore, JudgeVerdict
from harness.scenarios.models import CALMADO, ExpectedOutcome, Scenario
from harness.scoring import ScenarioResult
from harness.session import ConversationSession, ExchangeRecord


@pytest.fixture(autouse=True)
def _fake_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """`OpenAIChatCompletionClient` checks for a credential when constructed. The fake key
    satisfies that check; no test in this suite makes a network call."""
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-for-wiring-checks")


def make_session(
    *,
    category: str | None = None,
    level: str | None = None,
    clarifications: int = 0,
    corrections: int = 0,
    kiosk_says: list[str] | None = None,
    customer_says: list[str] | None = None,
    pii_types: list[str] | None = None,
    errors: list[str] | None = None,
) -> ConversationSession:
    session = ConversationSession(client=None, handle=SessionHandle("sid", "tok"))
    session.last_category = category
    session.last_consultation_level = level
    session.clarification_rounds = clarifications
    session.correction_rounds = corrections
    session.pii_types = pii_types or []
    session.errors = errors or []
    for index, text in enumerate(kiosk_says or []):
        session.exchanges.append(
            ExchangeRecord(
                index=index,
                tool="send_turn",
                customer_text=(customer_says or [None] * len(kiosk_says or []))[index]
                if customer_says
                else None,
                kiosk_speech=text,
            )
        )
    return session


def make_scenario(**overrides) -> Scenario:
    defaults = {
        "name": "escenario_de_prueba",
        "goal": "Necesitas algo del banco.",
        "tags": ("general_inquiry",),
        "style": CALMADO,
        "description": "A test scenario.",
        "expected": ExpectedOutcome(policy_notes="Nothing in particular."),
    }
    defaults.update(overrides)
    return Scenario(**defaults)


def make_verdict(score: int = 8, verdict: str = "PASS") -> JudgeVerdict:
    dimension = DimensionScore(score=score, reasoning="A sufficiently long dimension reason.")
    return JudgeVerdict(
        understanding=dimension,
        routing=dimension,
        policy_compliance=dimension,
        communication=dimension,
        resolution_quality=dimension,
        overall_score=score,
        reasoning="The kiosk handled the situation in the way this scenario called for, overall.",
        failures=[],
        strengths=["Clear next step."],
        verdict=verdict,
    )


def make_result(
    *,
    name: str = "escenario_de_prueba",
    group: str = "general_inquiry",
    score: int = 8,
    checks: list[CheckResult] | None = None,
    **overrides,
) -> ScenarioResult:
    defaults = {
        "scenario": name,
        "group": group,
        "tags": [group],
        "description": "A test scenario.",
        "final_status": "RESOLVED_AUTOMATIC",
        "checks": checks if checks is not None else [CheckResult("some_check", True, "ok")],
        "verdict": make_verdict(score),
        "expected_summary": "CONSULTA_GENERAL · GENERAL",
        "actual_summary": "CONSULTA_GENERAL · GENERAL",
        "exchanges": [
            ExchangeRecord(0, "send_turn", "Hola, quiero saber los horarios.", "¿Me confirmas?")
        ],
    }
    defaults.update(overrides)
    return ScenarioResult(**defaults)
