"""Kiosk orchestration, split by the three jobs the single module used to hold.

| Module | Job |
| --- | --- |
| `service` | lock the session, invoke the graph, dispatch the result |
| `responses` | shape graph state into `TurnAnalysisResponse` / `FlowResult` |
| `speech` | every sentence the kiosk says, and the plans that carry them |

`OrchestratorService` stays importable from `app.services.orchestrator`, so `api.deps`,
`api.kiosk`, `tests/conftest.py` and `tests/test_kiosk_flow.py` are unchanged.
"""

from app.services.orchestrator.service import OrchestratorService

__all__ = ["OrchestratorService"]
