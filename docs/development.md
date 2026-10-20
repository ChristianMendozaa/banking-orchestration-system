# Development

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

The application requires `APP_NAME`, `BANK_NAME`, `BRANCH_NAME`, `CORS_ORIGINS`,
`DATABASE_URL`, `JWT_SECRET`, `IDENTIFIER_PEPPER`, and the seed passwords from `.env`;
no deployment data or backup credentials live in code.

The read-only MCP server is a separate process on the same environment
(`uv run python -m app.mcp_server`, see [MCP servers](mcp.md)); knowledge-base CLI
commands are in [RAG](rag.md#knowledge-base-cli-and-worker).

| Endpoint | URL |
| --- | --- |
| OpenAPI | `http://localhost:8000/docs` |
| Readiness | `http://localhost:8000/api/v1/health/ready` |
| Public configuration | `http://localhost:8000/api/v1/system/public-config` |
| MCP | `http://localhost:8100/mcp` (health: `/healthz`) |

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
