# Intelligent Banking Service Orchestration Platform

An AI-assisted branch service platform that turns a natural-language customer request into either a grounded self-service answer or a prioritized, skill-based assignment to a human executive.

The system combines a voice-enabled kiosk, an executive workspace, a management dashboard, and a governed document knowledge base. Its orchestration layer masks personally identifiable information (PII), classifies intent, requests clarification and confirmation, applies deterministic priority rules, protects customer identification, and preserves an auditable case timeline.

> The platform orchestrates customer-service workflows and does not execute financial transactions. Any production deployment must complete the institution's security, compliance, and operational approval processes.

## Product overview

The platform supports three distinct operational experiences backed by one API and one database:

| Experience | Purpose | Default URL |
| --- | --- | --- |
| Customer kiosk | Voice-led request capture, clarification, confirmation, protected identification, self-service answers, and ticket delivery | `http://localhost:3000` |
| Executive workspace | Authenticated queue, assigned-case details, trace history, and controlled ticket transitions | `http://localhost:3001/ejecutivo` |
| Management workspace | Operational KPIs, filtered case reporting, and governed knowledge-document lifecycle | `http://localhost:3001/gerencial` |

The kiosk and staff applications are built from the same Next.js image but run as isolated surfaces. `APP_SURFACE` selects the permitted route family, and the application fails closed with `404` for pages or proxied API paths that belong to the other surface.

## Key capabilities

- **Voice-first accessible interaction** through OpenAI Realtime, with Spanish transcription, barge-in at any point including while a lookup runs, short-lived browser credentials, a complete scrollable PII-masked transcript that survives reconnects, and an always-available text alternative. The application owns the turn: it waits for the session's own Spanish transcription, sends it to the backend, and asks the model to say the outcome in its own words. What gets classified is that transcription, never the realtime model's retelling of it.
- **Privacy-first processing** that masks card numbers, account numbers, phone numbers, customer identifiers, monetary values, and names before classification or retrieval.
- **Structured request understanding** across card blocking, fraud reporting, general inquiries, credit requests, and digital banking.
- **Confirmation where confirmation is worth its cost**: a general question the kiosk is about to answer itself resolves in one turn, while anything personalized, sensitive, or flagged as a risk still has its summary read back before a case exists. Clarification and correction loops are bounded and idempotent per `turn_id`.
- **Deterministic safety floors over the classifier**, so an intermittently over-confident `GENERAL` label cannot skip identification or escalation on a request about the customer's own money.
- **Multi-need sessions**: a follow-up question after an automatic answer opens its own auditable case without a queue ticket, so someone who asks two things gets two answers.
- **Deterministic prioritization** based on category, urgency, security risk, distress signals, and preferential-attention policy.
- **Protected identification** for personalized and sensitive cases using an HMAC-derived identifier, masked display value, and a customer-reference registry.
- **Evidence-grounded answers** for eligible general inquiries using versioned PDF documents, pgvector retrieval, score thresholds, bounded context, and validated citations.
- **Human-in-the-loop fallback** whenever the request is sensitive, evidence is insufficient, grounding is invalid, the AI provider is unavailable, or classification remains ambiguous.
- **Skill-based case routing** that combines semantic fit, experience level, active workload, and deterministic tie-breaking.
- **Operational governance** through role-based access, optimistic concurrency, audited assignment and priority controls, executive availability, queue and SLA metrics, and asynchronous document lifecycle controls.

## Quickstart

Requires Docker Compose v2 and an OpenAI API key.

```bash
cp .env.example .env
cp backend/.env.example backend/.env   # replace every placeholder secret
docker compose up --build --remove-orphans
```

The kiosk is at `http://localhost:3000`, the staff workspace at `http://localhost:3001`, and the
API docs at `http://localhost:8000/docs`. Full setup, configuration, and local development
without Docker are in [docs/development.md](docs/development.md).

```bash
make install   # backend, evals, and frontend dependencies
make test      # hermetic suites, no services needed
make check     # full free gate: tests, coverage, lint, typecheck, build, contract drift
```

## Documentation

| Document | Covers |
| --- | --- |
| [Architecture](docs/architecture.md) | System and deployment diagrams, backend modules, technology stack, repository layout |
| [Kiosk orchestration](docs/orchestration.md) | Customer journey, orchestration policy, LangGraph graphs, agents, kiosk API sequence |
| [Frontend](docs/frontend.md) | Kiosk and staff surfaces, BFF proxy, kiosk turn handling, generated API types |
| [API](docs/api.md) | Endpoint families, access model, compatibility rules |
| [Data model](docs/data-model.md) | Entity diagram and migrations |
| [Retrieval-augmented generation](docs/rag.md) | Governed corpus, grounding rules, knowledge CLI and worker |
| [MCP server](docs/mcp.md) | Read-only domain MCP server |
| [Security and privacy](docs/security.md) | Controls for PII, credentials, sessions, and roles |
| [Development](docs/development.md) | Configuration, Docker Compose, local backend and frontend |
| [Testing](docs/testing.md) | Make targets, test categories, quality gates, CI |
| [Evaluation harness](docs/evaluation.md) | Live simulated-customer evaluation, judge, providers, latest evidence |
| [Operations](docs/operations.md) | Production readiness, observability, backup, rollback, retention |
