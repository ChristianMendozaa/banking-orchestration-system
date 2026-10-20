# Operations

The included Compose topology provides PostgreSQL/pgvector, Redis, ClamAV, migrations,
the document worker, API, and isolated web surfaces. Before a production deployment:

- Terminate TLS at a trusted reverse proxy and configure the exact public CORS origins.
- Store database credentials, `JWT_SECRET`, `IDENTIFIER_PEPPER`, seed passwords, and the Anthropic and OpenAI keys in a managed secret store.
- Configure a random `METRICS_TOKEN`, scrape `/internal/metrics`, centralize JSON logs,
  and apply the alert thresholds below.
- Define PostgreSQL backup, restore, migration rollback, and knowledge-file durability procedures.
- Review document approval and expiry policies, identity-verification rules, and data retention with the relevant security and compliance teams.
- Run dependency auditing and all backend/frontend quality gates in CI.

Keep Redis and ClamAV reachable only from the internal network; neither is meant to be
publicly exposed. Run `alembic upgrade head` before starting the API, worker, and MCP
process, then validate `/api/v1/health/ready` and the MCP process's `/healthz`, followed
by both web surfaces. Production configuration fails at startup if the Anthropic or OpenAI key, Redis, ClamAV,
a dedicated identifier-encryption key, or `METRICS_TOKEN` is missing.

## Services and observability

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

## Backup and restore

Take consistent backups of PostgreSQL and the `knowledge_data` volume. The document
archive and its metadata must be restored to the same logical point. Rehearse the restore
in an isolated environment at least quarterly:

1. restore the database and volume;
2. run `alembic current` and verify the expected revision;
3. run `python -m app.knowledge.cli status`;
4. exercise login, session creation, assignment, and document download;
5. compare document counts and hashes.

## Migration and rollback

Take a backup and review the new revision's SQL before migrating. If the application
fails after a deploy, revert the application version first. Only run `alembic downgrade`
when the revision documents a safe reversal — a migration that purges data cannot
reconstruct it.

Revision `20260813_0009` permanently drops the historical document-proposal table (see
[Data model](data-model.md#migrations) for the mechanical warning). Its downgrade can
recreate the structure but not the deleted rows; export that data before upgrading if a
retention obligation applies.

## Privacy and retention

Audio and the original transcript are not stored. Completed messages are re-masked in the
backend and purged once `CONVERSATION_RETENTION_DAYS` elapses. Closing a ticket deletes
the recoverable encrypted CI; its hash, masked value, and audit events remain.

Verify daily that the retention process ran, and document any exceptions.

The two keys are independent. Without `ANTHROPIC_API_KEY` in development, the deterministic keyword classifier takes over, an unclear confirmation is asked again, and RAG routes the case to a human. Without `OPENAI_API_KEY`, realtime voice returns a controlled `503`, executive routing skips semantic similarity, and RAG routes the case to a human because it cannot embed the query. Production configuration rejects either missing key at startup.
