# Repository Guidelines

## Project Structure & Change Map

This repository contains a Python 3.12 FastAPI backend and a Next.js 16/React 19 frontend. Start with these stable boundaries:

| Change | Inspect first |
| --- | --- |
| API endpoint or contract | `backend/app/main.py` wiring, `app/api/`, shared dependencies in `api/deps.py`, and `domain/enums.py` plus `domain/schemas/` |
| Kiosk or business orchestration | `api/kiosk.py` → `services/orchestrator/` (adapter, responses, speech) → LangGraph state/nodes in `services/graph/`; model and deterministic decisions live in `services/agents/`, `prompts/`, and `openai_provider.py` |
| Persistence or migration | Context-grouped ORM models in `db/models/`, repositories/session in `db/`, then `backend/alembic/versions/` |
| RAG or knowledge lifecycle | `api/knowledge.py`, `knowledge/` services/repository/indexing, background `knowledge/worker.py`, and governed sources in `doc/rag/` |
| Auth, authorization, or infrastructure | `api/auth.py`, `api/deps.py`, `core/security.py`, `core/config.py`; process wiring is in `main.py`, `mcp_server/`, and `docker-compose.yml` |
| Frontend route, UI, or API use | `frontend/app/`, `components/` (including providers), then `lib/api.ts`, `kiosk-api.ts`, `types.ts`, `app-surface.ts`, and the `app/backend-api/` proxy |
| Tests or model evaluation | `backend/tests/`, `frontend/tests/`, and the independent `backend/evals/` project (`harness/scenarios/`, `tests/`, and its README) |

Search for an existing service, schema, helper, component, or test pattern before adding one. Keep decisions in their existing layer instead of duplicating them in routes or UI. Prefer root Make targets over reconstructing equivalent commands. More specific nested instructions override this guide; read `frontend/AGENTS.md` before frontend changes.

## Build, Test, and Development Commands

Use the root Makefile as the canonical interface:

- `make install` synchronizes both `uv` projects and installs pnpm dependencies.
- `make test` runs all free, hermetic backend, harness, and frontend suites.
- `make lint` runs Ruff and ESLint checks.
- `make check` adds categorized tests, 90% backend coverage, type checking, frontend build, and OpenAPI drift detection.
- `make services-up` / `make services-down` manage local PostgreSQL, Redis, ClamAV, and backend services.

For focused work, use `make backend-test`, `make frontend-test`, or `make frontend-typecheck`. Run the nearest checks while iterating and `make check` for the full free gate before handoff. Migration changes also need an Alembic revision exercised against local PostgreSQL (`make services-up`). Run `make check-live` or any `make evals-*` target only intentionally; live/model evaluation may incur API or CLI-provider cost.

## Coding Style & Naming Conventions

Python uses four-space indentation, Ruff formatting, a 100-character line limit, and `snake_case`; classes use `PascalCase`. Frontend code uses strict TypeScript, ESLint, `PascalCase` components, `camelCase` functions, and generally kebab-case component filenames such as `ticket-card.tsx`; match the surrounding quote and semicolon style.

## Generated & Derived Artifacts

Do not hand-edit generated outputs:

- API/schema changes require `cd frontend && pnpm generate:api`, which updates `frontend/openapi.json` and `frontend/lib/generated-api.ts`; `make contract` is the CI drift gate and intentionally fails while those tracked outputs differ from `HEAD`.
- Changes under `backend/app/services/graph/` require `cd backend && PYTHONPATH=. uv run python scripts/render_graph_diagrams.py` to replace the marked README block.
- Managed RAG PDFs, `doc/rag/manifest.json`, and `doc/operacion/catalogo_perfiles_ejecutivos.pdf` come from `cd backend && uv run python scripts/render_operational_documents.py`.

## Testing Guidelines

Use Pytest for backend and eval tests and Vitest/Testing Library for frontend behavior. Name tests `test_<behavior>.py` or `<feature>.test.ts(x)`. Add applicable Pytest markers or Vitest tags: `unit`, `functional`, `integration`, `regression`, or `usability`. Every bug fix should include a regression test. Preserve the backend's 90% coverage minimum and configured frontend thresholds. Model/orchestration changes still require deterministic focused tests; use live evaluations as deliberate additional evidence, never as their replacement.

## Commit & Pull Request Guidelines

History favors short, imperative subjects (`Split schemas by surface`) and occasional Conventional Commit scopes (`fix(evals): ...`). Keep commits focused. Pull requests should explain user-visible and architectural effects, link issues, list validation commands, and include screenshots for UI changes. Call out migrations, configuration changes, generated contracts, and live-evaluation evidence.

## Security & Configuration

Copy `.env.example` files locally; never commit `.env`, API keys, passwords, customer identifiers, or raw sensitive transcripts. Preserve PII masking, role boundaries, audit trails, and human-handoff safety floors when changing orchestration behavior.

## Maintaining This Guide

Update `AGENTS.md` when architecture, directory ownership, canonical commands, conventions, generated workflows, or validation requirements change. Routine files added inside an already documented boundary do not require an update.
