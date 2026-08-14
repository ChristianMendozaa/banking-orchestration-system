# Intelligent Banking Service Orchestration Platform

An AI-assisted branch service platform that turns a natural-language customer request into either a grounded self-service answer or a prioritized, skill-based assignment to a human executive.

The system combines a voice-enabled kiosk, an executive workspace, a management dashboard, and a governed document knowledge base. Its orchestration layer masks personally identifiable information (PII), classifies intent, requests clarification and confirmation, applies deterministic priority rules, protects customer identification, and preserves an auditable case timeline.

> The platform orchestrates customer-service workflows and does not execute financial transactions. Any production deployment must complete the institution's security, compliance, and operational approval processes.

## Table of contents

- [Product overview](#product-overview)
- [Key capabilities](#key-capabilities)
- [System architecture](#system-architecture)
- [Customer journey](#customer-journey)
- [Backend design](#backend-design)
- [MCP server](#mcp-server)
- [Retrieval-augmented generation](#retrieval-augmented-generation)
- [Security and privacy](#security-and-privacy)
- [API overview](#api-overview)
- [Data model](#data-model)
- [Technology stack](#technology-stack)
- [Repository structure](#repository-structure)
- [Getting started](#getting-started)
- [Local development](#local-development)
- [Quality assurance](#quality-assurance)
- [Operational considerations](#operational-considerations)
- [Additional documentation](#additional-documentation)

## Product overview

The platform supports three distinct operational experiences backed by one API and one database:

| Experience | Purpose | Default URL |
| --- | --- | --- |
| Customer kiosk | Voice-led request capture, clarification, confirmation, protected identification, self-service answers, and ticket delivery | `http://localhost:3000` |
| Executive workspace | Authenticated queue, assigned-case details, trace history, and controlled ticket transitions | `http://localhost:3001/ejecutivo` |
| Management workspace | Operational KPIs, filtered case reporting, and governed knowledge-document lifecycle | `http://localhost:3001/gerencial` |

The kiosk and staff applications are built from the same Next.js image but run as isolated surfaces. `APP_SURFACE` selects the permitted route family, and the application fails closed with `404` for pages or proxied API paths that belong to the other surface.

## Key capabilities

- **Voice-first accessible interaction** through OpenAI Realtime, with Spanish transcription, interruptions, short-lived browser credentials, live captions, and an always-available text alternative.
- **Privacy-first processing** that masks card numbers, account numbers, phone numbers, customer identifiers, monetary values, and names before classification or retrieval.
- **Structured request understanding** across card blocking, fraud reporting, general inquiries, credit requests, and digital banking.
- **Explicit human confirmation** before a case is created, including clarification and correction loops with idempotent turn handling.
- **Deterministic prioritization** based on category, urgency, security risk, distress signals, and preferential-attention policy.
- **Protected identification** for personalized and sensitive cases using an HMAC-derived identifier, masked display value, and a customer-reference registry.
- **Evidence-grounded answers** for eligible general inquiries using versioned PDF documents, pgvector retrieval, score thresholds, bounded context, and validated citations.
- **Human-in-the-loop fallback** whenever the request is sensitive, evidence is insufficient, grounding is invalid, the AI provider is unavailable, or classification remains ambiguous.
- **Skill-based case routing** that combines semantic fit, experience level, active workload, and deterministic tie-breaking.
- **Operational governance** through role-based access, optimistic concurrency, audited assignment and priority controls, executive availability, queue and SLA metrics, and asynchronous document lifecycle controls.

## System architecture

```mermaid
flowchart LR
    Customer[Branch customer] --> Kiosk[Kiosk surface<br/>Next.js]
    Executive[Bank executive] --> Staff[Staff surface<br/>Next.js]
    Manager[Manager] --> Staff
    Eval[AutoGen evaluation harness] -.->|Kiosk REST contract| API

    Kiosk -->|Allowlisted BFF proxy| API[FastAPI application]
    Staff -->|Allowlisted BFF proxy| API
    Kiosk -.->|WebRTC with ephemeral secret| Realtime[OpenAI Realtime]

    subgraph Backend[Modular backend]
        API --> Auth[Authentication and RBAC]
        API --> Orchestrator[LangGraph kiosk orchestration]
        API --> Operations[Ticket and management APIs]
        API --> Knowledge[Knowledge management and RAG]
        Orchestrator --> Agents[Classification<br/>Prioritization<br/>Initial attention<br/>Derivation]
        Knowledge --> Agents
    end

    Auth --> PostgreSQL[(PostgreSQL 17<br/>pgvector)]
    Orchestrator --> PostgreSQL
    Operations --> PostgreSQL
    Knowledge --> PostgreSQL
    Knowledge --> Queue[Document job worker]
    Queue --> Documents[(Versioned PDF storage)]
    Knowledge --> Scanner[ClamAV]
    API --> Redis[(Redis rate limits)]
    Agents -->|Masked text only| OpenAI[OpenAI Responses<br/>and Embeddings]

    MCPClients[Authenticated external<br/>MCP clients] -->|Streamable HTTP /mcp<br/>staff JWT| MCP[MCP server<br/>read-only domain tools]
    MCP --> PostgreSQL
    MCP -->|Knowledge-search embeddings| OpenAI
```

The MCP server is a second ASGI process on its own port, sharing the backend's domain
code and PostgreSQL database without becoming part of the kiosk request path. The kiosk,
staff surfaces, and AutoGen harness use the REST API; authenticated external MCP clients
use `/mcp`. See [MCP server](#mcp-server).

### Deployment topology

Docker Compose defines an ordered startup pipeline. Migrations and deterministic operational seeding complete before knowledge ingestion, the API, and both frontend surfaces become available.

```mermaid
flowchart LR
    DB[(PostgreSQL + pgvector)] -->|healthy| Migrate[Alembic migrations<br/>and operational seed]
    Redis[(Redis)] --> API
    Redis -.->|Compose startup gate| MCP
    Scanner[ClamAV] --> API
    Migrate -->|completed| Bootstrap[Knowledge bootstrap]
    Bootstrap -->|completed| API[FastAPI backend]
    Bootstrap -->|completed| Worker[Knowledge worker]
    Bootstrap -->|completed| MCP[MCP server :8100]
    API -->|healthy| Kiosk[Kiosk frontend :3000]
    API -->|healthy| Staff[Staff frontend :3001]
    Bootstrap --> Volume[(Knowledge volume)]
```

## Customer journey

The backend owns the business state machine. The realtime agent provides the conversational channel, while controlled tools delegate analysis, confirmation, identification, retrieval, and ticket creation to the API.

```mermaid
sequenceDiagram
    autonumber
    actor Customer
    participant UI as Kiosk UI
    participant API as FastAPI
    participant Graph as LangGraph
    participant AI as AI services
    participant DB as PostgreSQL
    participant Exec as Executive

    Customer->>UI: Start session and describe the request
    UI->>API: Create kiosk session
    API-->>UI: Opaque session token
    UI->>API: Request realtime client secret
    API->>AI: Create restricted realtime session
    AI-->>UI: Ephemeral client secret

    UI->>API: Submit transcript with stable turn_id
    API->>Graph: Invoke turn_graph
    Graph->>Graph: Mask PII
    Graph->>AI: Classify masked request
    Graph->>Graph: Apply deterministic policy
    Graph->>DB: Persist session and requirement state

    alt Request is ambiguous
        Graph-->>API: Request clarification
        API-->>UI: Ask one clarification question
        Customer->>UI: Provide clarification
        UI->>API: Submit clarification turn
    end

    Graph-->>API: Return next action and summary
    API-->>UI: Present customer-facing summary
    Customer->>UI: Confirm or correct
    UI->>API: Submit confirmation
    API->>Graph: Invoke confirmation_graph

    alt Personalized or sensitive request
        Graph-->>API: Require protected identification
        API-->>UI: Request customer identity-card number (CI) in protected field
        UI->>API: Submit identifier outside the voice transcript
        API->>Graph: Invoke identification_graph
        Graph->>DB: Store protected identifier and finalize
    end

    alt Eligible general inquiry with sufficient evidence
        Graph->>AI: Retrieve and generate from approved evidence
        Graph->>DB: Persist citations and audit outcome
        API-->>UI: Grounded answer with sources
    else Human service required
        Graph->>DB: Rank executives and create ticket
        API-->>UI: Ticket, desk, executive, and wait estimate
        Exec->>API: Progress ticket through controlled states
    end
```

### Orchestration policy

The kiosk flow is implemented as three [LangGraph](https://github.com/langchain-ai/langgraph)
graphs (`app/services/graph/`), one per API entry point, sharing a compiled `finalize`
subgraph. The diagrams below are generated directly from the compiled graphs via
`graph.get_graph().draw_mermaid()` -- from `backend/`, run
`PYTHONPATH=. uv run python scripts/render_graph_diagrams.py` after any change to
`app/services/graph/*.py` to regenerate this section, so it cannot drift from the
implementation. Dashed edges are dynamic `Command`-based routing (guard and
replay-idempotency branches, e.g. an already-completed turn short-circuiting to its cached
result); solid edges are static and dashed-with-labels are conditional policy branches.

No LangGraph checkpointer is used: each HTTP request is already the unit of work, and
`SessionStatus` on the `kiosk_sessions` row -- read under `SELECT ... FOR UPDATE` on
PostgreSQL -- is the durable, queryable record of where a session is in the flow. See the
module docstring in `app/services/graph/state.py` for the full reasoning.

The application imports LangGraph directly. LangChain Core provides the underlying graph
runtime abstractions through LangGraph's dependency tree; there is no separate LangChain
agent layer in the kiosk.

<!-- BEGIN GENERATED GRAPH DIAGRAMS -->

#### `turn_graph`

Handles `POST /kiosk/sessions/{id}/turns`.

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	guard_turn(guard_turn)
	mask_pii(mask_pii)
	classify(classify)
	clarify(clarify)
	force_human(force_human)
	accept(accept)
	persist_requirement(persist_requirement)
	__end__([<p>__end__</p>]):::last
	__start__ --> guard_turn;
	accept --> persist_requirement;
	clarify --> persist_requirement;
	classify -.-> accept;
	classify -.-> clarify;
	classify -.-> force_human;
	force_human --> persist_requirement;
	guard_turn -.-> __end__;
	guard_turn -.-> mask_pii;
	mask_pii --> classify;
	persist_requirement --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

#### `confirmation_graph`

Handles `POST /kiosk/sessions/{id}/confirmation`. `finalize` is the shared subgraph below, reused verbatim by `identification_graph`.

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	load_and_guard(load_and_guard)
	heal_decision(heal_decision)
	handle_replay(handle_replay)
	validate_fresh_confirmation(validate_fresh_confirmation)
	apply_confirmation(apply_confirmation)
	finalize(finalize)
	__end__([<p>__end__</p>]):::last
	__start__ --> load_and_guard;
	apply_confirmation -.-> __end__;
	apply_confirmation -.-> finalize;
	handle_replay -.-> __end__;
	handle_replay -.-> finalize;
	handle_replay -.-> validate_fresh_confirmation;
	heal_decision -. &nbsp;replay&nbsp; .-> handle_replay;
	heal_decision -. &nbsp;fresh&nbsp; .-> validate_fresh_confirmation;
	load_and_guard --> heal_decision;
	validate_fresh_confirmation -.-> __end__;
	validate_fresh_confirmation -.-> apply_confirmation;
	finalize --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

#### `identification_graph`

Handles `POST /kiosk/sessions/{id}/identification`.

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	guard_identification(guard_identification)
	resolve_client_reference(resolve_client_reference)
	persist_identification(persist_identification)
	finalize(finalize)
	__end__([<p>__end__</p>]):::last
	__start__ --> guard_identification;
	guard_identification -.-> __end__;
	guard_identification -.-> resolve_client_reference;
	persist_identification --> finalize;
	resolve_client_reference --> persist_identification;
	finalize --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

#### `finalize_subgraph`

Compiled once in `builder.py` and added as the `finalize` node to both graphs above -- the same compiled instance, not a copy.

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	ticket_guard(ticket_guard)
	assign_priority(assign_priority)
	attempt_grounding(attempt_grounding)
	automatic_ticket(automatic_ticket)
	route_human(route_human)
	persist_ticket(persist_ticket)
	__end__([<p>__end__</p>]):::last
	__start__ --> ticket_guard;
	assign_priority -.-> attempt_grounding;
	assign_priority -.-> route_human;
	attempt_grounding -.-> automatic_ticket;
	attempt_grounding -.-> route_human;
	automatic_ticket --> persist_ticket;
	route_human --> persist_ticket;
	ticket_guard -.-> __end__;
	ticket_guard -.-> assign_priority;
	persist_ticket --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```
<!-- END GENERATED GRAPH DIAGRAMS -->

## Backend design

The backend is a modular monolith: deployment remains simple, while API, domain, persistence, orchestration, AI-provider, and knowledge responsibilities stay explicitly separated.

| Module | Responsibility |
| --- | --- |
| `app/api` | HTTP contracts, dependency injection, kiosk session authorization, staff RBAC, pagination, and filters |
| `app/services/orchestrator.py` | Thin adapter: session locking, invoking the LangGraph graphs below, and shaping their final state into API responses |
| `app/services/graph` | The state machine itself -- turn/confirmation/identification graphs, the shared `finalize` subgraph, guard and idempotency logic (see [Orchestration policy](#orchestration-policy)) |
| `app/services/agents.py` | Classification fallback, deterministic priority rules, evidence eligibility, and executive ranking |
| `app/services/openai_provider.py` | Structured model calls, embeddings, grounded generation, and realtime client-secret creation |
| `app/services/pii.py` | Local PII detection and masking before downstream AI processing |
| `app/knowledge` | PDF extraction, chunking, ingestion, retrieval, grounding validation, evaluation, and management lifecycle |
| `app/mcp_server` | Read-only MCP tools for authenticated external clients -- bearer-authenticated, streamable-HTTP, never called by the frontends (see [MCP server](#mcp-server)) |
| `app/db` | Async SQLAlchemy models, repositories, session management, and idempotent operational seeding |
| `alembic` | Explicit, ordered schema migrations including pgvector and the HNSW vector index |
| `evals/` (standalone project) | AutoGen persona-simulation harness scoring policy compliance against a live backend; own venv and CI job, not part of the modular backend (see [Quality assurance](#quality-assurance)) |

### Specialized orchestration components

| Component | Decision boundary |
| --- | --- |
| `ClassificationAgent` | Produces a validated structured category, consultation level, confidence, ambiguity status, customer-facing summary, and risk signals. A conservative local fallback is available in development. |
| `PrioritizationAgent` | Assigns `BAJO`, `MEDIO`, `ALTO`, or `CRITICO` through deterministic banking rules; preferential attention can raise non-high priorities by one level. |
| `InitialAttentionAgent` | Allows automatic answers only for `GENERAL` requests and only when `KnowledgeService` returns a grounded, naturally worded response. |
| `DerivationAgent` | Filters to available executives with the required category, then ranks by semantic match (70%), experience (20%), and workload (10%). |

Concurrency-sensitive kiosk operations lock the session row on PostgreSQL. Stable `turn_id` values, unique database constraints, recorded confirmation decisions, and one-ticket-per-case constraints make client retries safe. Ticket updates use an `expected_version` field and a closed transition graph:

```text
PENDIENTE -> EN_ATENCION -> CERRADO
```

## MCP server

`app/mcp_server/` runs as a second ASGI application (`python -m app.mcp_server`, port
`8100`) using the backend image and domain code but a separate process and database
connection pool. It exposes five read-only tools over MCP's streamable-HTTP transport to
authenticated external MCP clients. The kiosk and staff frontends call the typed REST
API, while the [AutoGen eval harness](backend/evals/README.md) exercises that same kiosk
REST contract. Neither the LangGraph nodes nor the AutoGen harness call MCP.

| Tool | Returns |
| --- | --- |
| `search_knowledge` | pgvector evidence for a query, scoped to a category -- fragments with citation and similarity score, never a generated answer |
| `get_case_trace` | The auditable `TraceEvent` timeline for a case, PII-masked |
| `list_executive_availability` | Available executives, active workload, and category skills |
| `get_ticket_status` | Ticket status, priority, estimated wait, and assigned executive -- never the customer identifier |
| `explain_routing_decision` | Recomputes `DerivationAgent`'s full ranking (semantic match 70%, experience 20%, workload 10%) without mutating the case |

```mermaid
flowchart LR
    Client[Authenticated external<br/>MCP client] -->|Streamable HTTP /mcp<br/>staff JWT| Auth[BearerAuthMiddleware]
    Auth --> Tools[Five read-only tools]
    Tools --> Domain[domain.py]
    Domain --> PostgreSQL[(PostgreSQL 17)]
    Domain -->|search_knowledge,<br/>explain_routing_decision| OpenAI[OpenAI embeddings]
```

Authentication reuses the same JWT and role model as the staff REST API
(`decode_access_token`, `UserRole.EXECUTIVE` / `UserRole.MANAGER`) rather than a parallel
scheme. The check is inlined as raw ASGI middleware (`app/mcp_server/auth.py`) instead of
Starlette's `BaseHTTPMiddleware`, which buffers the response body and is unsafe for MCP's
streaming transport. The server never exposes kiosk-session mutation or identifier
reveal -- those operations stay exclusive to the authenticated REST API.

Run it locally alongside the backend:

```bash
cd backend
uv run python -m app.mcp_server
curl http://localhost:8100/healthz
```

After obtaining an executive or manager access token through the REST authentication
API, configure the MCP client to connect to `http://localhost:8100/mcp` with
`Authorization: Bearer <access-token>`.

## Retrieval-augmented generation

The knowledge subsystem is governed rather than open-ended. It indexes only registered PDF documents and refuses to answer when retrieval or citation validation fails.

```mermaid
flowchart LR
    Manifest[Versioned manifest] --> Validate[Validate PDF,<br/>metadata, and SHA-256]
    Upload[Manager upload] --> Validate
    Validate --> Extract[Extract text by page]
    Extract --> Chunk[Section-aware token chunks]
    Chunk --> Embed[OpenAI embeddings]
    Embed --> Index[(pgvector HNSW index)]

    Query[Masked query] --> QueryEmbed[Query embedding]
    QueryEmbed --> Retrieve[Cosine retrieval]
    Index --> Retrieve
    Retrieve --> Policy[Active, current,<br/>category, and score filters]
    Policy --> Generate[Structured grounded answer]
    Generate --> Verify{All citations belong to<br/>retrieved evidence?}
    Verify -->|Yes| Answer[Answer and citations]
    Verify -->|No| Human[Human fallback]
    Policy -->|No evidence| Human
```

An automatic response requires all of the following:

1. The request is classified as a general consultation and is not marked for forced human handling.
2. The query has already been masked.
3. Retrieved documents are active, within their review period, category-compatible, and above the configured similarity threshold.
4. The prompt context stays within the configured token budget.
5. The model returns a supported structured response with at least one citation.
6. Every cited chunk belongs to the exact retrieved evidence set.

Every retrieval attempt records its outcome, prompt version, retrieved chunk metadata, and an answer hash when applicable. The raw generated answer is not duplicated in the RAG audit record.

Managers can list, upload, update, version, download, reindex, and archive knowledge documents. Upload validation covers PDF signature, MIME type, file size, page count, extractable text, category metadata, and HTTP(S) source URLs; stored objects use generated UUID keys instead of user-supplied filenames.

## Security and privacy

The implementation applies defense-in-depth controls appropriate to the project scope:

- Raw audio is handled by the realtime channel and is not persisted by the application.
- Original audio and unmasked transcripts are not stored. Completed dialogue messages are masked again by the backend, retained for 90 configurable days, and then purged automatically.
- PINs, CVVs, passwords, credentials, and complete financial data are explicitly prohibited in realtime and grounded-answer instructions.
- The regular OpenAI API key never reaches the browser. The browser receives only a short-lived realtime client secret tied to the kiosk session.
- Kiosk access uses a high-entropy opaque token; only its SHA-256 hash is stored, and every protected kiosk route validates expiry.
- Customer identity-card numbers (CI) keep the HMAC-SHA-256 digest and masked suffix, plus an AES-256-GCM encrypted value protected by a versioned key. Only the assigned executive can reveal it, and every reveal is audited.
- Staff passwords use the recommended Argon2 password hash.
- Staff access uses short-lived HS256 JWTs. Opaque refresh tokens are stored as hashes, rotated on use, revocable, and delivered through `HttpOnly`, `SameSite=Lax` cookies (`Secure` in production).
- RBAC separates `EXECUTIVE` and `MANAGER`. Executives can access only their assigned tickets and reveal only those identifiers; managers receive masked, read-only case files, reporting, and knowledge-management permissions.
- Ticket transitions are allowlisted and guarded by optimistic concurrency. A partial unique constraint permits only one active attendance per executive, and closing requires a structured outcome and protected note.
- API errors share a stable contract with `code`, `message`, `details`, and `trace_id`; structured request logs include the same trace correlation header.
- Login, kiosk-session creation, and realtime-token creation have basic per-process rate limits.
- Application settings validate secret length, CORS origins, vector dimensions, retrieval limits, and mandatory AI configuration in production.

## API overview

All versioned endpoints are exposed under `/api/v1`. Interactive OpenAPI documentation is available at `http://localhost:8000/docs`.

Existing endpoints are treated as compatibility contracts even when the bundled frontend does
not call them. Removal requires observed usage data, an OpenAPI deprecation marker, documented
notice, and a compatibility window; repository search alone is never sufficient evidence.

| Area | Representative endpoints | Access model |
| --- | --- | --- |
| Health | `GET /health/live`, `GET /health/ready` | Public |
| Public configuration | `GET /system/public-config` | Public |
| Staff authentication | `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me` | Credentials, refresh cookie, or bearer token |
| Kiosk workflow | `POST /kiosk/sessions`, turns, confirmation, identification, conversation-message synchronization, and session status | Opaque `X-Session-Token` after creation |
| Realtime voice | `POST /kiosk/sessions/{id}/realtime-token` | Opaque `X-Session-Token` |
| Executive operations | Filtered `GET /executive/tickets`, `GET /tickets/{id}`, status transitions, and identifier reveal | Executive bearer token; managers have masked read-only ticket-detail access |
| Management reporting | `GET /management/metrics`, `GET /management/cases` | Manager bearer token |
| Knowledge governance | `/management/knowledge/documents` and document version, reindex, download, and archive operations | Manager bearer token |

The two Next.js surfaces call these endpoints through `/backend-api/api/v1/...`, a same-origin backend-for-frontend proxy that forwards only the API families allowlisted for the active surface.

## Data model

```mermaid
erDiagram
    USER ||--o| EXECUTIVE : owns_profile
    USER ||--o{ REFRESH_SESSION : authenticates_with
    EXECUTIVE ||--o{ EXECUTIVE_SKILL : has
    EXECUTIVE ||--o{ TICKET : receives

    KIOSK_SESSION ||--o{ REQUIREMENT : captures
    KIOSK_SESSION ||--o{ CONVERSATION_MESSAGE : retains_masked
    KIOSK_SESSION ||--o| CASE_RECORD : creates
    REQUIREMENT ||--o| CASE_RECORD : confirms
    CASE_RECORD ||--o| IDENTIFICATION : verifies
    CLIENT_REFERENCE ||--o{ IDENTIFICATION : matches
    CASE_RECORD ||--o| TICKET : produces
    CASE_RECORD ||--o{ TRACE_EVENT : records
    CASE_RECORD ||--o{ RAG_INTERACTION : audits

    KNOWLEDGE_DOCUMENT ||--o{ KNOWLEDGE_CHUNK : contains

    USER {
        uuid id PK
        string email
        enum role
        boolean active
    }
    KIOSK_SESSION {
        uuid id PK
        string access_token_hash
        enum status
        datetime expires_at
    }
    CASE_RECORD {
        uuid id PK
        enum category
        enum priority
        enum consultation_level
        enum identification_status
    }
    TICKET {
        integer number PK
        uuid public_id
        enum status
        enum resolution_outcome
        integer version
    }
    KNOWLEDGE_DOCUMENT {
        uuid id PK
        string slug
        string version
        enum index_status
        boolean active
    }
    KNOWLEDGE_CHUNK {
        uuid id PK
        integer page
        integer token_count
        vector embedding
    }
```

Schema evolution is managed by nine ordered Alembic revisions covering the operational
model, pgvector knowledge schema, production hardening, the natural kiosk flow, the
protected staff case file, and compatibility-safe retirement of superseded schema.

## Technology stack

| Layer | Technologies |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS 4, Recharts, OpenAI Agents SDK, Zod |
| Backend | Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 async, Uvicorn, Structlog |
| AI | OpenAI Realtime, structured Responses API calls, text embeddings, LangGraph on LangChain Core (kiosk state machine), MCP (external read-only domain tools), AutoGen (offline REST-based policy evaluation) |
| Data | PostgreSQL 17, pgvector, HNSW cosine index, Alembic |
| Security | Argon2, JWT access tokens, rotating opaque refresh tokens, HMAC identifier protection |
| Tooling | Docker Compose, `uv`, `pnpm`, Ruff, Pytest, Vitest, ESLint |

## Repository structure

```text
.
├── backend/
│   ├── alembic/                 # Versioned database migrations
│   ├── app/
│   │   ├── api/                 # FastAPI routers and access dependencies
│   │   ├── core/                # Configuration, errors, security, time helpers
│   │   ├── db/                  # Models, repositories, sessions, operational seed
│   │   ├── domain/              # Enums and Pydantic contracts
│   │   ├── knowledge/           # Ingestion, retrieval, RAG, document management
│   │   ├── mcp_server/          # Read-only MCP tools for authenticated external clients
│   │   └── services/            # Orchestrator adapter, LangGraph graphs, agents, PII, OpenAI provider
│   ├── evals/                   # Standalone AutoGen policy-evaluation harness (own project)
│   ├── seed/                    # Deterministic branch and executive catalog
│   └── tests/                   # Backend unit and integration suite
├── frontend/
│   ├── app/                     # Kiosk, executive, and management routes
│   ├── components/              # Product and UI components
│   ├── lib/                     # API client, realtime logic, domain types
│   └── tests/                   # Surface isolation and realtime behavior tests
├── doc/
│   ├── rag/                     # Governed source PDFs and manifest
│   └── operacion/               # Generated operational documentation
├── docker-compose.yml           # Complete local topology and startup ordering
└── .env.example                 # Compose-level configuration template
```

## Getting started

### Prerequisites

- Docker Engine with Docker Compose v2
- An OpenAI API key for realtime voice, model-based classification, embeddings, and grounded answers
- Available local ports `3000`, `3001`, `8000`, and `5432` (or custom values in `.env`)

### 1. Create local configuration

```bash
cp .env.example .env
cp backend/.env.example backend/.env
```

Replace every placeholder password and secret in both files. At minimum, configure:

```dotenv
# .env
POSTGRES_DB=orquestacion
POSTGRES_USER=orquestacion
POSTGRES_PASSWORD=<strong-local-database-password>

# backend/.env
OPENAI_API_KEY=<your-api-key>
JWT_SECRET=<at-least-32-random-characters>
IDENTIFIER_PEPPER=<a-different-random-secret>
SEED_EXECUTIVE_PASSWORD=<at-least-12-characters>
SEED_MANAGER_PASSWORD=<at-least-12-characters>
```

Do not commit `.env` files or expose `OPENAI_API_KEY`. The configured `KIOSK_FRONTEND_ORIGIN` and `STAFF_FRONTEND_ORIGIN` must match the browser-visible origins, including deployments behind reverse proxies.

### 2. Start the platform

```bash
docker compose up --build --remove-orphans
```

On the first run, Compose creates the database, applies all migrations, loads the operational registry, indexes the manifest-managed knowledge corpus when `OPENAI_API_KEY` is present, starts the API, and then exposes both frontend surfaces.

### 3. Verify the deployment

```bash
docker compose ps
curl http://localhost:8000/api/v1/health/ready
curl -I http://localhost:3000/
curl -I http://localhost:3001/
```

Expected behavior:

- Port `3000` redirects `/` to `/kiosco`.
- Port `3001` redirects `/` to `/login`.
- The readiness endpoint returns `{"status":"ready"}` after PostgreSQL is reachable.
- API documentation is available at `http://localhost:8000/docs`.

Operational users are seeded from `backend/seed/operational_seed.json`; their passwords come exclusively from `SEED_EXECUTIVE_PASSWORD` and `SEED_MANAGER_PASSWORD`.

## Local development

### Backend

Run PostgreSQL with the `vector` extension, then execute from `backend/`:

```bash
uv sync
uv run alembic upgrade head
uv run python -m app.db.seed
uv run python -m app.knowledge.cli ingest
uv run uvicorn app.main:app --reload
```

In another terminal, start the document job processor:

```bash
uv run python -m app.knowledge.worker
```

The backend reads `backend/.env`. `DATABASE_URL` is used by the async application, while `DATABASE_MIGRATION_URL` can provide a separate migration connection.

Knowledge-base operations:

```bash
uv run python -m app.knowledge.cli ingest
uv run python -m app.knowledge.cli status
uv run python -m app.knowledge.cli evaluate
```

`ingest` validates the manifest and content hashes, extracts and chunks PDFs, creates embeddings, updates document versions, and backfills executive-skill embeddings. `evaluate` runs retrieval cases and verifies that policy-ineligible requests are not answered automatically.

### Frontend

Run either development surface from `frontend/`:

```bash
pnpm install --frozen-lockfile
APP_SURFACE=kiosk BACKEND_INTERNAL_URL=http://localhost:8000 pnpm dev
```

```bash
PORT=3001 APP_SURFACE=staff BACKEND_INTERNAL_URL=http://localhost:8000 pnpm dev
```

Run one surface at a time when using the shared local `.next` directory. Use Docker Compose to run both isolated surfaces simultaneously.

## Quality assurance

The backend suite covers kiosk state transitions, ambiguity and correction loops, idempotent retries, protected identification, priority rules, PII masking, role boundaries, refresh rotation, realtime-secret containment, RAG ingestion and grounding, executive routing, management metrics, and knowledge-document lifecycle.

`.github/workflows/ci.yml` runs on every pull request and on push to `main`. It skips backend or
frontend jobs when the corresponding path did not change, runs the backend test suite on Python
3.12 and 3.14, uploads coverage artifacts, and fails the run if the OpenAPI contract or the
generated TypeScript types drift from what `generate:api` produces.

### Running everything with one command

A root `Makefile` wraps every suite -- backend, `backend/evals`, and frontend -- behind three
entry points. Run `make help` for the full target list.

```bash
make install   # uv sync (backend/, backend/evals/) + pnpm install --frozen-lockfile (frontend/)
make test      # the hermetic suites only: backend pytest, evals pytest, frontend vitest
make check     # everything CI runs, plus the evals suites CI doesn't, plus the live harness
```

`make test` needs nothing running -- it's the fast, free path for everyday iteration. `make
check` adds linting, typechecking, `next build`, the OpenAPI contract-drift check, and the live
AutoGen harness described below (`evals-live`); it starts `docker compose` and reads
`OPENAI_API_KEY` and `MAX_CLARIFICATIONS` straight out of `backend/.env`, so nothing is duplicated
or hardcoded in the Makefile itself -- if the key is absent, `evals-live` is reported as `SKIP`
rather than failing the run. Every suite runs regardless of earlier failures, and `make check`
ends with one summary table (suite, PASS/FAIL/SKIP, duration) and a non-zero exit if anything
failed.

Each target also runs standalone, e.g. `make backend-test` or `make frontend-lint`, if you only
want one suite.

### What each target runs

Backend validation (`backend-lint`, `backend-test`, `backend-coverage` -- equivalent to running
these from `backend/`):

```bash
uv run ruff format --check .
uv run ruff check .
uv run coverage run -m pytest -q
uv run coverage report
```

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

[`backend/evals/`](backend/evals/README.md) additionally ships a separate, standalone-project
**live** policy evaluation harness (`make evals-live`, or `uv run python -m harness` from
`backend/evals/`): an AutoGen agent plays one of five customer personas and drives a real kiosk
session turn by turn against a **live** backend, and a deterministic (non-LLM) evaluator in
`harness/evaluator.py` scores the finished session against the orchestration policy -- did a
fraud report reach `CRITICO`, was a sensitive case identified before it resolved, was every
automatic answer cited. Its coverage is intentionally kept out of `backend/`'s `fail_under=90`
gate, and there is no CI workflow for the live run -- each run makes real, billed OpenAI calls on
both sides (the simulated customer and the backend's own classification/RAG), so it stays a
manual, local-only check against a `docker compose` backend rather than something triggered from
a PR.

Dependency auditing (`uv run --with pip-audit pip-audit`, `pnpm audit`) is not run in CI; run it
locally before releases if you want to check for known vulnerabilities.

## Operational considerations

The included Compose topology provides PostgreSQL/pgvector, Redis, ClamAV, migrations,
the document worker, API, and isolated web surfaces. Before a production deployment:

- Terminate TLS at a trusted reverse proxy and configure the exact public CORS origins.
- Store database credentials, `JWT_SECRET`, `IDENTIFIER_PEPPER`, seed passwords, and the OpenAI key in a managed secret store.
- Configure a random `METRICS_TOKEN`, scrape `/internal/metrics`, centralize JSON logs,
  and apply the alert thresholds below.
- Define PostgreSQL backup, restore, migration rollback, and knowledge-file durability procedures.
- Review document approval and expiry policies, identity-verification rules, and data retention with the relevant security and compliance teams.
- Run dependency auditing and all backend/frontend quality gates in CI.

Keep Redis and ClamAV reachable only from the internal network; neither is meant to be
publicly exposed. Run `alembic upgrade head` before starting the API, worker, and MCP
process, then validate `/api/v1/health/ready` and the MCP process's `/healthz`, followed
by both web surfaces. Production configuration fails at startup if OpenAI, Redis, ClamAV,
a dedicated identifier-encryption key, or `METRICS_TOKEN` is missing.

### Services and observability

- The API publishes liveness and readiness under `/api/v1/health`.
- The MCP process publishes `/healthz`; its `/mcp` endpoint requires a valid executive or
  manager JWT and must not be exposed outside the network intended for authorized MCP
  clients.
- Prometheus can scrape `/internal/metrics` with `Authorization: Bearer <METRICS_TOKEN>`.
- Logs are JSON, include `trace_id`, normalized route, status, and duration, and never
  record customer text or identifiers.
- The `app.knowledge.worker` process claims jobs with locking, recovers interrupted jobs,
  and keeps the previously active document when a reindex fails.

Recommended baseline alerts:

- 5xx response rate above 2% for 5 minutes;
- HTTP p95 above 2 seconds for 10 minutes;
- rate-limit rejections growing anomalously;
- readiness failing for 2 minutes;
- the MCP process health check failing for 2 minutes;
- document jobs failed or running for more than 15 minutes;
- critical or unassigned cases above the operational threshold;
- the oldest pending case's age above the defined SLA.

### Backup and restore

Take consistent backups of PostgreSQL and the `knowledge_data` volume. The document
archive and its metadata must be restored to the same logical point. Rehearse the restore
in an isolated environment at least quarterly:

1. restore the database and volume;
2. run `alembic current` and verify the expected revision;
3. run `python -m app.knowledge.cli status`;
4. exercise login, session creation, assignment, and document download;
5. compare document counts and hashes.

### Migration and rollback

Take a backup and review the new revision's SQL before migrating. If the application
fails after a deploy, revert the application version first. Only run `alembic downgrade`
when the revision documents a safe reversal — a migration that purges data cannot
reconstruct it.

Revision `20260813_0009` permanently drops the historical document-proposal table (see
[`backend/README.md`](backend/README.md) for the mechanical warning). Its downgrade can
recreate the structure but not the deleted rows; export that data before upgrading if a
retention obligation applies.

### Privacy and retention

Audio and the original transcript are not stored. Completed messages are re-masked in the
backend and purged once `CONVERSATION_RETENTION_DAYS` elapses. Closing a ticket deletes
the recoverable encrypted CI; its hash, masked value, and audit events remain.

Verify daily that the retention process ran, and document any exceptions.

When OpenAI is intentionally absent in development, deterministic classification fallback remains available, realtime voice returns a controlled `503`, and RAG safely routes the case to a human. Production configuration rejects a missing OpenAI key at startup.

## Additional documentation

- [Backend implementation guide](backend/README.md)
- [Governed RAG manifest](doc/rag/manifest.json)
- [Orchestration policy evaluation harness (AutoGen)](backend/evals/README.md)
