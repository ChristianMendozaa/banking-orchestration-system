# Testing and quality gates

The backend suite covers kiosk state transitions, ambiguity and correction loops, idempotent retries, protected identification, priority rules, PII masking, role boundaries, refresh rotation, realtime-secret containment, RAG ingestion and grounding, executive routing, management metrics, and knowledge-document lifecycle.

`.github/workflows/ci.yml` runs on every pull request and on push to `main`. A push whose commit
was merged from a pull request skips every job, since that PR's run already covered it; direct
pushes to `main` run in full. It skips backend or frontend jobs when the corresponding path did
not change, runs the backend test suite on Python 3.12 and 3.14, uploads coverage artifacts, and
fails the run if the OpenAPI contract or the generated TypeScript types drift from what
`generate:api` produces.

## Test commands and evidence

A root `Makefile` wraps every suite -- backend, `backend/evals`, and frontend -- behind three
entry points. Run `make help` for the full target list.

```bash
make install   # uv sync (backend/, backend/evals/) + pnpm install --frozen-lockfile (frontend/)
make test      # the hermetic suites only: backend pytest, evals pytest, frontend vitest
make check     # all free required test categories plus quality gates; never runs live evals
make check-live # deliberate maximum validation: check, then billed live evaluation
```

`make test` and `make check` need nothing running. `make check` adds the five categorized,
non-billed suites, linting, typechecking, `next build`, coverage gates, and the OpenAPI
contract-drift check. It does not require `backend/.env`, Docker, `OPENAI_API_KEY`, or a live
harness. Its final report is grouped by the five categories and quality gates, then
shows the newest saved live-evaluation metrics as informational historical evidence. Every suite
runs despite earlier failures, and the final status is non-zero when a current automated check
failed.

The five required categories intentionally overlap, so the Makefile totals are test executions,
not a count of unique tests. All category commands are deterministic and local: they need neither
Docker, a running backend, `OPENAI_API_KEY`, nor a model call.

| Command | Runs | Cost and use |
| --- | --- | --- |
| `make unit-test` | Isolated backend rules, frontend components/hooks/utilities, and mocked harness internals | Free; use while developing a component or rule. |
| `make functional-test` | Critical kiosk, text, RAG, staff, and realtime behavior | Free; use to demonstrate requirements and user flows. |
| `make integration-test` | API, services, SQLite persistence, auth, RAG, MCP, and frontend boundary collaboration using local/fake dependencies | Free; use after changes spanning layers. |
| `make regression-test` | Documented fixes, classifier-floor scenarios, idempotency/state-machine behavior, and realtime ordering | Free; use before merging a fix or milestone. |
| `make usability-test` | Automated accessibility and clarity support checks, including labelled controls, live announcements, explicit choices, and scoped axe checks | Free; it supports but does not replace testing with participants. |
| `make check` | Every free category plus coverage, lint, type-check, build, and OpenAPI contract quality gates | Free normal validation; displays the newest saved live-evaluation metrics without rerunning it. |
| `make evals-live` | Live Docker backend, simulated LLM customer, deterministic evaluator, and LLM judge | Deliberate billed validation. |
| `make evals-live-codex` / `make evals-live-claude-code` | The same live backend evaluation through the named local CLI provider | Deliberate billed validation; backend model calls still require `OPENAI_API_KEY`. |
| `make check-live` | `make check`, then `make evals-live` | Maximum milestone validation; can incur API cost. |

Coverage, linting, type checking, frontend build, and OpenAPI drift checks are quality gates,
not substitutes for the five test categories. The live harness complements deterministic tests:
its evaluator enforces policy facts and its LLM judge evaluates qualities rules cannot fully
decide. Neither a good judge score nor automated accessibility checks demonstrates human
usability; participant observation, tasks, consent, and findings remain a manual study.

Each target also runs standalone, e.g. `make backend-test` or `make frontend-lint`, if you only
want one suite.

## What each target runs

Backend validation (`backend-lint`, `backend-test`, `backend-coverage` -- equivalent to running
these from `backend/`):

```bash
uv run ruff format --check .
uv run ruff check .
uv run coverage run -m pytest -q
uv run coverage report
```

`make transcript-fidelity` is separate from the suites: it audits real voice sessions in the
running database rather than testing code. For every spoken turn it compares the voice
session's own transcription against the text the classifier was actually given, and exits
non-zero on any divergence. That invariant is the one a live kiosk session broke on
2026-08-19, and it is checkable against branch traffic without any audio harness:

```bash
cd backend && PYTHONPATH=. uv run python scripts/check_transcript_fidelity.py --since-hours 24
```

The live evaluation harness is documented in [evaluation.md](evaluation.md).

`backend/evals`' own suite is mocked and makes no LLM calls (`evals-lint`, `evals-test` --
equivalent to running these from `backend/evals/`):

```bash
uv run ruff check .
uv run pytest -q
```

Frontend validation (`frontend-lint`, `frontend-typecheck`, `frontend-test`, `frontend-build`,
`contract` -- equivalent to running these from `frontend/`):

```bash
pnpm lint
pnpm typecheck
pnpm test:coverage
pnpm build
pnpm generate:api
```

`generate:api` exports FastAPI's OpenAPI schema and regenerates the TypeScript contracts used by
the frontend; `make check`'s `contract` target then fails on any drift. Backend and frontend
suites are hermetic: the backend test environment uses an isolated ephemeral SQLite schema and
deterministic AI doubles, and does not call OpenAI or read `backend/.env` (`APP_ENV=test` forces
`Settings` to skip loading it, so a developer's local Redis/ClamAV/OpenAI configuration never
leaks into a test run). None of `make test`, `make lint`, `backend-build`, or `contract` needs
Docker Compose or any other service running.

Dependency auditing (`uv run --with pip-audit pip-audit`, `pnpm audit`) is not run in CI; run it
locally before releases if you want to check for known vulnerabilities.
