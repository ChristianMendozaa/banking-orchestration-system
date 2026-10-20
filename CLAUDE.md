# Banking orchestration system

AI-assisted bank-branch service platform. A customer speaks (or types) a request at a kiosk;
the system either answers it from a governed document corpus with citations, or creates a
prioritized ticket routed to the best-matched human executive. Staff surfaces cover the
executive queue and a management dashboard with knowledge-document governance. It
orchestrates service workflows only — it never executes financial transactions.

The whole repo is worked on from the root: Python 3.12 FastAPI backend in `backend/`,
Next.js 16 / React 19 frontend in `frontend/`, a standalone eval project in `backend/evals/`.
Customer-facing text and domain enums are Spanish; code, comments, and docs are English.

## How it fits together

- **Two frontend surfaces, one image.** `APP_SURFACE=kiosk` (port 3000, `/kiosco`) or
  `staff` (port 3001, `/login`, `/ejecutivo`, `/gerencial`). Each only serves its own pages
  and proxies only its allowlisted API families through `/backend-api/...`
  (`frontend/lib/app-surface.ts`). → [docs/frontend.md](docs/frontend.md)
- **Backend decides, the voice model speaks.** The browser owns the turn: it takes the
  realtime session's own Spanish transcription, sends it to the backend, and asks the
  tool-less realtime model to voice the returned `SpeechPlan`. Every decision — PII masking,
  classification, priority, clarification budget, identification, evidence, routing — is
  the backend's. → [docs/orchestration.md](docs/orchestration.md)
- **Kiosk flow = three LangGraph graphs** (`turn_graph`, `confirmation_graph`,
  `identification_graph`) sharing one compiled `finalize` subgraph, under
  `backend/app/services/graph/`. `services/orchestrator/` is a thin adapter (session
  locking, response shaping, speech). No checkpointer: the `kiosk_sessions` row, locked with
  `SELECT ... FOR UPDATE`, is the durable state.
- **Agents** in `services/agents/`: `ClassificationAgent` (model + deterministic
  `sensitivity_floor` that only ever raises the level), `PrioritizationAgent` and
  `DerivationAgent` (deterministic rules / weighted ranking), `InitialAttentionAgent`
  (grounded answers for `GENERAL` only). Prompts are policy and live in `services/prompts/`.
- **Model providers**: decisions (classification, confirmation reading, grounded answers) go
  to Claude Haiku 5.5 via `services/anthropic_provider.py` (`messages.parse` structured
  outputs, effort-controlled). Embeddings (pgvector is fixed at 1536 dims) and realtime voice
  stay on OpenAI via `services/openai_provider.py`.
- **RAG** is governed: only manifest-registered PDFs in `doc/rag/`, pgvector retrieval,
  citations validated against retrieved chunks; any gap routes to a human.
  → [docs/rag.md](docs/rag.md)
- **MCP server**: `backend/app/mcp_server/` (read-only, staff-JWT) for external clients. The
  kiosk never uses MCP. → [docs/mcp.md](docs/mcp.md)
- **Persistence**: async SQLAlchemy models grouped by context in `db/models/`
  (`identity`, `kiosk`, `operations`, `knowledge`), explicit Alembic revisions.
  → [docs/data-model.md](docs/data-model.md)

## Where to look

| Change | Inspect first | Read |
| --- | --- | --- |
| API endpoint or contract | `backend/app/main.py` wiring, `app/api/`, shared deps in `api/deps.py`, `domain/enums.py` and `domain/schemas/` | [api.md](docs/api.md) |
| Kiosk or business orchestration | `api/kiosk.py` → `services/orchestrator/` (`service.py`, `responses.py`, `speech.py`) → `services/graph/`; decisions in `services/agents/`, `prompts/`, `anthropic_provider.py` | [orchestration.md](docs/orchestration.md) |
| Kiosk voice / client turn logic | `frontend/components/providers/kiosk-provider.tsx`, `frontend/lib/kiosk-realtime.ts`, `kiosk-realtime-agent.ts` | [frontend.md](docs/frontend.md) |
| Persistence or migration | `db/models/`, repositories/session in `db/`, `backend/alembic/versions/` | [data-model.md](docs/data-model.md) |
| RAG or knowledge lifecycle | `api/knowledge.py`, `app/knowledge/` (service, repository, indexing, `uploads.py`, `worker.py`), `doc/rag/` | [rag.md](docs/rag.md) |
| Auth, roles, infrastructure | `api/auth.py`, `api/deps.py`, `core/security.py`, `core/config.py`, `main.py`, `mcp_server/`, `docker-compose.yml` | [security.md](docs/security.md), [operations.md](docs/operations.md) |
| Frontend route, UI, API use | `frontend/app/`, `components/` (incl. providers), `lib/api.ts`, `kiosk-api.ts`, `types.ts`, `app-surface.ts`, `app/backend-api/` | [frontend.md](docs/frontend.md) |
| Tests or model evaluation | `backend/tests/`, `frontend/tests/`, `backend/evals/` (`harness/scenarios/`, `tests/`) | [testing.md](docs/testing.md), [evaluation.md](docs/evaluation.md) |

Search for an existing service, schema, helper, component, or test pattern before adding
one. Keep each decision in its existing layer instead of duplicating it in routes or UI.

## Commands

Use the root Makefile; don't reconstruct equivalent commands. `make help` lists everything.

- `make install` — sync both `uv` projects and pnpm dependencies.
- `make test` — hermetic backend, harness, and frontend suites; nothing needs to run.
- `make lint` — Ruff and ESLint.
- `make check` — free full gate: five test categories, 90% backend coverage, typecheck,
  `next build`, OpenAPI drift. Run before handing work off.
- Focused: `make backend-test`, `make frontend-test`, `make frontend-typecheck`,
  `make unit-test` / `functional-test` / `integration-test` / `regression-test` /
  `usability-test`.
- `make services-up` / `make services-down` — local PostgreSQL, Redis, ClamAV, backend.
  Needed to exercise a new Alembic revision against real PostgreSQL.
- **Costs money — only when explicitly intended:** `make check-live` and every
  `make evals-*` target (live backend + billed Anthropic and OpenAI model calls).

## Conventions

- Python: 4-space indent, Ruff format, 100-char lines, `snake_case`, `PascalCase` classes.
- Frontend: strict TypeScript, ESLint, `PascalCase` components, `camelCase` functions,
  kebab-case filenames (`ticket-card.tsx`); match surrounding quote/semicolon style.
- Tests: `test_<behavior>.py` with `pytestmark = [pytest.mark.<category>]`;
  `<feature>.test.ts(x)` with a `// @module-tag <category>` header. Categories: `unit`,
  `functional`, `integration`, `regression`, `usability`.
- Every bug fix gets a regression test. Keep backend coverage ≥ 90% and the frontend
  thresholds.
- Model/orchestration changes need deterministic focused tests; live evals are additional
  evidence, never a replacement.
- Commits: short imperative subjects (`Split schemas by surface`), occasional scopes
  (`fix(evals): ...`), one concern per commit. PRs explain user-visible and architectural
  effects, list validation commands, include screenshots for UI, and call out migrations,
  config changes, generated contracts, and live-eval evidence.

## Generated files — never hand-edit

- `frontend/openapi.json`, `frontend/lib/generated-api.ts` ← `cd frontend && pnpm generate:api`
  after any API/schema change. `make contract` fails while they differ from `HEAD`.
- The `GENERATED GRAPH DIAGRAMS` block in `docs/orchestration.md` ←
  `cd backend && PYTHONPATH=. uv run python scripts/render_graph_diagrams.py` after any change
  under `backend/app/services/graph/`.
- `doc/rag/*.pdf`, `doc/rag/manifest.json`, `doc/operacion/catalogo_perfiles_ejecutivos.pdf`
  ← `cd backend && uv run python scripts/render_operational_documents.py`.

## Invariants — do not weaken

- PII is masked locally (`services/pii.py`) before any classification, retrieval, or
  storage; audio and unmasked transcripts are never persisted.
- Deterministic floors beat the model: `sensitivity_floor` only raises the consultation
  level; `REPORTE_FRAUDE`, `security_incident`, or `distress_detected` always force
  confirmation; exhausted clarification/correction budgets hand off to a human.
- Automatic answers only for `GENERAL`, only with valid citations to retrieved evidence;
  anything else goes to a person.
- Role boundaries: executives see only their own tickets and may reveal only those CIs
  (audited); managers get masked, read-only case data.
- Audit trail (`TraceEvent`) is preserved for every decision.
- Never commit `.env` files, API keys, passwords, customer identifiers, or raw transcripts.

## Frontend: Next.js 16

This is not the Next.js in most training data: APIs, conventions, and file structure
changed (e.g. route middleware is `frontend/proxy.ts`). Before writing Next-specific code,
read the relevant guide in `frontend/node_modules/next/dist/docs/` and heed deprecations.

## Keeping docs current

`docs/` is the reference; this file is the map. When a change alters behavior described in
a doc, update that doc in the same change (orchestration policy → `orchestration.md`,
endpoints → `api.md`, a migration → the list in `data-model.md`, Make targets →
`testing.md`, eval scenarios or providers → `evaluation.md`). Update this file when
architecture, directory ownership, commands, conventions, or generated workflows change.
