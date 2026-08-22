"""The four kiosk agents, one per module, plus the deterministic rules under `rules/`.

| Module | Decision it owns |
| --- | --- |
| `classification` | category, consultation level, confidence, ambiguity, risk signals |
| `prioritization` | BAJO / MEDIO / ALTO / CRITICO -- pure, synchronous, no model call |
| `derivation` | which executive a case goes to, and the estimated wait behind them |
| `initial_attention` | whether the corpus can answer this without a person |

Everything the previous single `agents.py` module exported is re-exported here, so
`from app.services.agents import ...` keeps working unchanged for callers, tests and
`scripts/probe_classifier.py` (which imports the private `_LEVEL_ORDER`).
"""

from app.services.agents.classification import ClassificationAgent
from app.services.agents.derivation import DerivationAgent, DerivationDecision
from app.services.agents.initial_attention import InitialAttentionAgent
from app.services.agents.prioritization import PrioritizationAgent
from app.services.agents.rules.categories import category_from_keywords
from app.services.agents.rules.language import (
    customer_facing_text_is_natural,
    customer_summary_for,
    grounded_answer_is_natural,
)
from app.services.agents.rules.sensitivity import _LEVEL_ORDER, sensitivity_floor

__all__ = [
    "ClassificationAgent",
    "DerivationAgent",
    "DerivationDecision",
    "InitialAttentionAgent",
    "PrioritizationAgent",
    "_LEVEL_ORDER",
    "category_from_keywords",
    "customer_facing_text_is_natural",
    "customer_summary_for",
    "grounded_answer_is_natural",
    "sensitivity_floor",
]
