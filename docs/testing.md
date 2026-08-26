# Test commands and evidence

The five required test categories are intentionally overlapping. A test may provide evidence
for several categories, so the totals in Makefile reports are test executions, not unique tests.
All category commands are deterministic and local: they do not require Docker, a running
backend, `OPENAI_API_KEY`, or a model call.

| Command | Runs | Cost and use |
| --- | --- | --- |
| `make unit-test` | Isolated backend rules, frontend components/hooks/utilities, and mocked harness internals | Free; use while developing a component or rule. |
| `make functional-test` | Critical kiosk, text, RAG, staff, and realtime behavior | Free; use to demonstrate requirements and user flows. |
| `make integration-test` | API, services, SQLite persistence, auth, RAG, MCP, and frontend boundary collaboration using local/fake dependencies | Free; use after changes spanning layers. |
| `make regression-test` | Documented fixes, classifier-floor scenarios, idempotency/state-machine behavior, and realtime ordering | Free; use before merging a fix or milestone. |
| `make usability-test` | Automated accessibility and clarity support checks, including labelled controls, live announcements, explicit choices, and scoped axe checks | Free; it is not a substitute for testing with human participants. |
| `make check` | Every free category plus coverage, lint, type-check, build, and OpenAPI contract quality gates | Free normal validation. It also displays the newest saved live-evaluation metrics without re-running it. |
| `make evals-live` | Live Docker backend, simulated LLM customer, deterministic evaluator, and LLM judge | Deliberate billed validation. |
| `make evals-live-codex` / `make evals-live-claude-code` | The same live backend evaluation through the named local CLI provider | Deliberate billed validation; backend model calls still require `OPENAI_API_KEY`. |
| `make check-live` | `make check`, then `make evals-live` | Maximum milestone validation; can incur API cost. |

## Quality gates and live-evaluation evidence

Coverage, linting, type checking, frontend build, and OpenAPI drift checks are **quality gates**,
not substitutes for the five test categories. `make check` keeps the existing backend
and frontend coverage thresholds intact.

The harness in `backend/evals/` complements, rather than replaces, deterministic tests. Its
mocked internal suite is part of unit evidence. A deliberate live run offers higher-level
functional, integration, regression, and communication-quality evidence against a real backend.
The deterministic evaluator enforces policy facts; the LLM judge assesses qualities that rules
cannot fully decide. Neither a good judge score nor automated accessibility checks demonstrate
human usability: participant observation, tasks, consent, and findings remain a manual study.

`make check` reads only the newest existing `backend/evals/reports/runs/*/report.json`. The
informational block shows its revision, models, scenario outcome, score, policy checks, and path.
It never changes the check result, and a missing or malformed saved report does not fail free
validation. A fresh clone can therefore show no saved live report until someone intentionally
runs an `evals-live*` command.
