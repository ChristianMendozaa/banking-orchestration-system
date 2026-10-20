# API

All versioned endpoints are exposed under `/api/v1`. Interactive OpenAPI documentation is available at `http://localhost:8000/docs`.

Existing endpoints are treated as compatibility contracts even when the bundled frontend does
not call them. Removal requires observed usage data, an OpenAPI deprecation marker, documented
notice, and a compatibility window; repository search alone is never sufficient evidence.

| Area | Representative endpoints | Access model |
| --- | --- | --- |
| Health | `GET /health/live`, `GET /health/ready` | Public |
| Public configuration | `GET /system/public-config` | Public |
| Staff authentication | `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me` | Credentials, refresh cookie, or bearer token |
| Kiosk workflow | `POST /kiosk/sessions`, turns, confirmation, identification, PII-masked conversation synchronization/history, and session status | Opaque `X-Session-Token` after creation |
| Realtime voice | `POST /kiosk/sessions/{id}/realtime-token` | Opaque `X-Session-Token` |
| Executive operations | Filtered `GET /executive/tickets`, `GET /tickets/{id}`, status transitions, and identifier reveal | Executive bearer token; managers have masked read-only ticket-detail access |
| Management reporting | `GET /management/metrics`, `GET /management/cases` | Manager bearer token |
| Knowledge governance | `/management/knowledge/documents` and document version, reindex, download, and archive operations | Manager bearer token |

The turns endpoint answers `CLARIFY`, `CONFIRM`, `DECLINE`, or -- when a confident general
request resolved without a confirmation step -- `COMPLETE` with the full `result` (grounded
answer and citations, or ticket, desk, executive, and wait estimate) already embedded, so the
kiosk needs no second call. The generated TypeScript contract in `frontend/lib/generated-api.ts`
is regenerated from the same OpenAPI schema and checked for drift in CI.

The two Next.js surfaces call these endpoints through `/backend-api/api/v1/...`, a same-origin backend-for-frontend proxy that forwards only the API families allowlisted for the active surface.
