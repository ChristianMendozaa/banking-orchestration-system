"""The scenario catalog.

44 scenarios across eight groups, assembled here so `--tag` and `--scenario` can select
across all of them and so a structural test can assert the catalog stays coherent.

| Group | Tag | What it is for |
| --- | --- | --- |
| Card and fraud | `card_fraud` | The highest-stakes path: priority, identification, no PII echo |
| General inquiry | `general_inquiry` | Grounded answers; refusing to answer with no evidence |
| Digital and credit | `digital_credit` | `BANCA_DIGITAL` coverage; the GENERAL/PERSONALIZADA line |
| Conversation flow | `flow` | Clarification limits, the correction loop, topic changes |
| Accessibility | `accessibility` | Preferential attention, comprehension of difficult speech |
| Adversarial | `adversarial` | Injection, out-of-scope transactions, credentials, hostility |
| Transcription noise | `asr_noise` | Corrupted transcripts: no confident misroute |
| Protocol | `protocol` | State-machine guards against the live PostgreSQL stack |
"""

from harness.scenarios import (
    accessibility,
    adversarial,
    asr_noise,
    card_and_fraud,
    conversation_flow,
    digital_and_credit,
    general_inquiry,
    protocol,
)
from harness.scenarios.models import (
    ExpectedOutcome,
    PersonaStyle,
    Scenario,
    ScenarioCatalog,
)

SCENARIOS: list[Scenario] = [
    *card_and_fraud.SCENARIOS,
    *general_inquiry.SCENARIOS,
    *digital_and_credit.SCENARIOS,
    *conversation_flow.SCENARIOS,
    *accessibility.SCENARIOS,
    *adversarial.SCENARIOS,
    *asr_noise.SCENARIOS,
    *protocol.SCENARIOS,
]

CATALOG = ScenarioCatalog(tuple(SCENARIOS))

# Order used to group rows and bars in the dashboard.
GROUP_ORDER = (
    "card_fraud",
    "general_inquiry",
    "digital_credit",
    "flow",
    "accessibility",
    "adversarial",
    "asr_noise",
    "protocol",
)

GROUP_LABELS = {
    "card_fraud": "Card & fraud",
    "general_inquiry": "General inquiry",
    "digital_credit": "Digital & credit",
    "flow": "Conversation flow",
    "accessibility": "Accessibility",
    "adversarial": "Adversarial",
    "asr_noise": "Transcription noise",
    "protocol": "Protocol",
}


def all_tags() -> list[str]:
    return sorted({tag for scenario in SCENARIOS for tag in scenario.tags})


__all__ = [
    "CATALOG",
    "GROUP_LABELS",
    "GROUP_ORDER",
    "SCENARIOS",
    "ExpectedOutcome",
    "PersonaStyle",
    "Scenario",
    "ScenarioCatalog",
    "all_tags",
]
