# Backend FastAPI

Modular monolith implementing the banking orchestration flow: privacy, classification,
disambiguation, prioritization, protected verification, RAG response, skill-based
derivation, tickets, traces, executive operation, management metrics, and document
governance.

To run the complete system see [`../README.md`](../README.md).

## Local setup

Requirements: Python 3.12 or later, `uv`, and PostgreSQL with the `vector` extension.

```bash
uv sync
uv run alembic upgrade head
uv run python -m app.db.seed
uv run python -m app.knowledge.cli ingest
uv run uvicorn app.main:app --reload
```

In another terminal, the read-only MCP server starts as an independent ASGI process
that reuses this same environment:

```bash
uv run python -m app.mcp_server
```

The application requires `APP_NAME`, `BANK_NAME`, `BRANCH_NAME`, `CORS_ORIGINS`,
`DATABASE_URL`, `JWT_SECRET`, `IDENTIFIER_PEPPER`, and the seed passwords from `.env`;
no deployment data or backup credentials live in code. Copy `.env.example` only if
`.env` doesn't exist yet, and replace every marked value. Never publish
`OPENAI_API_KEY`.

`BRANCH_NAME` is where the kiosk thinks it is standing, and it is not only a heading on
the screen: it is given to the model that writes grounded answers, which scopes a question
about the branch, its schedule or its address to that one branch instead of reciting the
whole network. Set it to the branch the machine is actually installed in. `get_settings()`
is cached for the life of the process, so changing it takes a backend restart.

- OpenAPI: `http://localhost:8000/docs`
- Health: `http://localhost:8000/api/v1/health/ready`
- Public configuration: `http://localhost:8000/api/v1/system/public-config`
- MCP: `http://localhost:8100/mcp`
- MCP health: `http://localhost:8100/healthz`

## Kiosk and agents

1. `POST /api/v1/kiosk/sessions` creates a short-lived session with an opaque token.
2. Subsequent calls use `X-Session-Token`.
3. `POST .../realtime-token` creates an ephemeral secret for WebRTC. The regular API
   key never leaves the backend.
4. `POST .../turns` masks PII and classifies. `turn_id` makes the operation idempotent.
5. The flow responds `CLARIFY`, `CONFIRM`, `DECLINE`, or `COMPLETE`. `COMPLETE` means a
   confident `GENERAL` request skipped confirmation and finalized inside the same request,
   with the answer or ticket already in `result` (`turn_nodes.requires_confirmation`).
   A `REPORTE_FRAUDE` category or a `security_incident` / `distress_detected` flag always
   forces `CONFIRM`, whatever consultation level the model returned.
6. `POST .../confirmation` allows correction or starts finalization, where priority is
   applied and the case is created. Rejecting the summary `MAX_CORRECTIONS` times (default
   2) records a `CORRECTION_LIMIT_REACHED` trace event and derives the case to an executive
   instead of asking again.
7. The `PERSONALIZADA` and `SENSIBLE` levels request the customer's CI through a
   protected field.
8. `GENERAL` inquiries attempt RAG; any evidence gap routes to a person.
9. A further question after an automatic answer reopens the session
   (`RESOLVED_AUTOMATIC` -> `LISTENING`, per-need counters reset) and produces a second case
   and ticket; `cases.session_id` is no longer unique. `ASSIGNED` sessions are excluded --
   an executive already holds that case.

`app/services/orchestrator.py` is a thin adapter over three LangGraph graphs:
`turn_graph`, `confirmation_graph`, and `identification_graph`. All three reuse the one
compiled `finalize` subgraph, which applies priority, attempts a grounded answer, and,
when applicable, routes to a person -- `turn_graph` reaches it through `auto_capture` when
a request resolves without a confirmation step. LangGraph uses LangChain Core abstractions
as an underlying dependency; the kiosk does not maintain a second LangChain agent layer.

Agents have separated responsibilities:

- `ClassificationAgent`: category, level, ambiguity, and risk signals. `sensitivity_floor`
  raises the level the model returned when the text is about the customer's own money,
  plastic, or access (source `MODEL+FLOOR`); it never lowers it, and shares its keyword
  tables with the offline fallback.
- `PrioritizationAgent`: deterministic priority and preferential attention.
- `InitialAttentionAgent`: response for the general level only, with RAG evidence.
- `DerivationAgent`: exact skill, semantic similarity, experience, and workload.

Audio and the original transcript are not persisted. Realtime keeps the conversation
speech-to-speech and the browser syncs only completed messages; the backend re-masks
them before storing and purges them according to the configured retention. The
Realtime agent's tools delegate classification, confirmation, RAG, identification, and
tickets to the backend via REST.

The CI keeps the HMAC digest and masked suffix for comparison and listings.
Additionally, it is encrypted with AES-256-GCM so only the assigned executive can
reveal it during active attendance. Closing purges the recoverable value; the query and
the purge are both audited, and management always receives the masked value.

## Knowledge base

Bootstrap consumes exclusively `../doc/rag/manifest.json`; it does not generate
documents at runtime.

```bash
uv run python -m app.knowledge.cli ingest
uv run python -m app.knowledge.cli status
uv run python -m app.knowledge.cli evaluate
```

- `ingest`: validates the manifest/hash, extracts text, chunks, and generates
  embeddings.
- `status`: reports active documents and chunks.
- `evaluate`: tests retrieval and also classifies cases where policy prohibits an
  automatic response.

The management API under `/api/v1/management/knowledge/documents` allows listing,
uploading, editing, versioning, downloading, reindexing, and archiving. Indexing jobs
are queued and `python -m app.knowledge.worker` processes them with recoverable
retries. Before storage, ClamAV scans the file; PDF signature, MIME type, size, page
count, extractable text, category, and HTTP(S) source URL are also verified. Files are
stored with UUID keys; the original filename is metadata only.

An automatic response requires:

- an already-masked query;
- an active, non-expired document;
- a compatible category and similarity above the threshold;
- a structured response bounded to the retrieved evidence;
- at least one valid citation to a retrieved chunk.

Any failure of these conditions creates a human ticket.

## MCP server

`app/mcp_server` exposes five read-only tools to external MCP clients:
`search_knowledge`, `get_case_trace`, `list_executive_availability`,
`get_ticket_status`, and `explain_routing_decision`. It uses streamable HTTP transport
at `/mcp`, requires a valid executive or manager JWT, and shares domain functions and
PostgreSQL with the API without sharing its process.

MCP is not part of the kiosk path. The frontends, the LangGraph graphs, and the eval
harness's kiosk contract all use the REST API. (`evals/harness/mcp_kiosk_server.py` is a
separate, localhost-only MCP server that exists only during an eval run, so a local
`claude` / `codex` CLI can play the customer; it does not ship.) `search_knowledge` and
`explain_routing_decision` are the only MCP tools that may use OpenAI — the first for
query embedding, the second because it reuses `DerivationAgent` for the case's semantic
ranking; the other three query domain state without mutating it and without depending
on the provider. `/healthz` is public for health checks, but `/mcp` always goes through
`BearerAuthMiddleware`.

## Persistence and migrations

Migrations are explicit and frozen:

- `20260716_0001`: operational schema;
- `20260716_0002`: pgvector, documents, chunks, and RAG interactions;
- `20260716_0003`: expiry, proposed priority, and document lifecycle.
- `20260717_0004`: customer registry, internal sources, and estimated wait.
- `20260720_0005`: natural flow, idempotent confirmation, and recoverable state.
- `20260721_0006`: operational case file, retained conversation, and structured
  closure.
- `20260728_0007`: document queue, management controls, and closure privacy.
- `20260813_0008`: historical revision kept for deployment compatibility.
- `20260813_0009`: permanent retirement of the historical document-proposal table.
- `20260818_0010`: drops the unique constraint on `cases.session_id` so one kiosk session
  can hold several cases; `tickets.case_id` stays unique.

Upgrading to `0009` deletes any records that may exist in that table. Take a backup
before migrating if you need to keep them; a downgrade reconstructs only the empty
structure.

`Base.metadata.create_all()` is not used in migrations. Tests do create an isolated
ephemeral SQLite schema.

## Authorization

- Short-lived access JWT held in frontend memory.
- Opaque refresh token, rotated and stored as a hash; `HttpOnly`, `SameSite=Lax`, and
  `Secure` (in production) cookie.
- `EXECUTIVE` and `MANAGER` roles.
- An executive can only query their own tickets; management accesses metrics and
  knowledge.
- Ticket states use optimistic versioning and closed transitions.

## Verification

From the repo root, `make test` (hermetic suites only) or `make check` (everything, including
lint/typecheck/build and the live evals harness) run this project alongside `evals/` and
`frontend/` with one command and a single pass/fail summary -- see the root
[README's "Running everything with one command"](../README.md#running-everything-with-one-command).
Equivalently, from `backend/`:

```bash
uv run ruff format --check .
uv run ruff check .
uv run coverage run -m pytest -q
uv run coverage report
uv run --with pip-audit pip-audit
```

Tests do not consume OpenAI, do not read `backend/.env` (`APP_ENV=test` short-circuits that in
`app/core/config.py`, so a developer's local Redis/ClamAV/OpenAI settings never leak into a test
run), and cover the general flow, clarification, correction, identification, priority, privacy,
RAG, expiry, roles, refresh, concurrency, and the document lifecycle.

The policy evaluation harness lives as an independent project in
[`evals/`](evals/README.md). A simulated customer drives 42 scenarios against a real REST
API turn by turn; each finished session is scored by a deterministic, non-LLM evaluator and
by an LLM judge, with any failed hard check capping the score at 4/10 whatever the judge
thought. Both the customer and the judge can run on OpenAI or on a local `claude` / `codex`
CLI. Its unit tests do not consume OpenAI:

```bash
cd evals
uv sync
uv run pytest
```

The end-to-end run is billed and has no CI workflow; it is launched manually against a running
local backend (`docker compose up`, or `make evals-live` / `make evals-live-codex` from the repo
root, which read `OPENAI_API_KEY`, `MAX_CLARIFICATIONS` and `RAG_MIN_SCORE` from `backend/.env`),
never on every PR. `OPENAI_API_KEY` pays for the backend under test in every mode, including the
CLI-backed ones.

To regenerate the executive catalog and the managed operational documents:

```bash
uv run python scripts/render_operational_documents.py
```
