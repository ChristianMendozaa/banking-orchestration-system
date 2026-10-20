# Frontend

One Next.js 16 / React 19 application in `frontend/`, built into one image and run as two
isolated **surfaces**. Strict TypeScript, Tailwind CSS 4, Vitest + Testing Library.

> Next.js 16 has breaking changes relative to older versions (APIs, conventions, file
> structure). Before writing Next-specific code, read the relevant guide in
> `frontend/node_modules/next/dist/docs/` and heed deprecation notices. Route middleware lives
> in `proxy.ts`, not `middleware.ts`.

## Surfaces

`APP_SURFACE` (`kiosk` or `staff`) selects which routes and API families a process serves.
`lib/app-surface.ts` is the single allowlist:

| Surface | Pages | Proxied API prefixes | Default port |
| --- | --- | --- | --- |
| `kiosk` | `/kiosco/**` | `/api/v1/kiosk`, `/api/v1/system/public-config` | 3000 |
| `staff` | `/login`, `/ejecutivo/**`, `/gerencial/**` | `/api/v1/auth`, `/api/v1/executive`, `/api/v1/tickets`, `/api/v1/management`, `/api/v1/system/public-config` | 3001 |

Everything outside the active surface fails closed with `404`:

- `proxy.ts` redirects `/` to the surface home, returns `404` for foreign pages, `503` when
  `APP_SURFACE` is unset, and sets a nonce-based Content-Security-Policy on every response
  (`connect-src` allows only self and `api.openai.com` for WebRTC).
- `app/backend-api/[...path]/route.ts` is the same-origin backend-for-frontend proxy. The
  browser calls `/backend-api/api/v1/...`; the route checks the path against the surface
  allowlist and forwards to `BACKEND_INTERNAL_URL`. The browser never talks to FastAPI
  directly.

A new backend endpoint the UI needs must be added to `API_PREFIXES` in `lib/app-surface.ts`
(and covered in `tests/app-surface.test.ts` / `tests/backend-api.test.ts`).

## Layout

| Path | Contents |
| --- | --- |
| `app/kiosco/` | Kiosk pages: start (`page.tsx`), `voz` (voice conversation), `identificacion` (protected CI entry), `respuesta` (terminal decline), `ticket` |
| `app/(staff)/` | `login`, `ejecutivo` (queue and case detail), `gerencial` (KPIs, cases, `conocimiento` document management) |
| `components/providers/` | `kiosk-provider.tsx` (kiosk state machine and realtime session), `auth-provider.tsx` (staff auth), `system-config-provider.tsx` (public config) |
| `components/kiosk`, `executive`, `management`, `ui` | Surface components and shared primitives |
| `lib/api.ts` | `apiRequest` over `/backend-api/api/v1` and `ApiError` (`code`, `details`, `trace_id` from the backend error contract) |
| `lib/kiosk-api.ts` | Kiosk REST calls and the realtime client-secret shape |
| `lib/kiosk-realtime.ts` | Pure kiosk turn logic: routing, confirmation parsing, speech-plan data, mic policy, caption merging |
| `lib/kiosk-realtime-agent.ts` | Builds the tool-less `RealtimeAgent` from the persona the backend minted |
| `lib/types.ts` | Domain types re-exported from `lib/generated-api.ts` |
| `lib/generated-api.ts`, `openapi.json` | **Generated** — never hand-edit; run `pnpm generate:api` |

## API contract

Types come from the backend's OpenAPI schema: `pnpm generate:api` exports it from FastAPI and
runs `openapi-typescript` into `lib/generated-api.ts`. `lib/types.ts` aliases the schemas the
UI uses. Any backend schema change must be followed by regeneration; `make contract` fails
on drift.

## Staff authentication

`auth-provider.tsx` keeps the short-lived access JWT in memory only. The refresh token is an
`HttpOnly` cookie set by the backend; the provider de-duplicates concurrent refreshes and
restores the session on load through `POST /auth/refresh`.

## Kiosk turn handling

The backend owns business state; the browser owns the turn (see
[Kiosk orchestration](orchestration.md#customer-journey) for the full policy). In code:

- The realtime agent has **no tools** and `create_response` is off. Persona, voice, model and
  audio-input config come back with the client secret from `POST .../realtime-token`; the
  browser must not keep a second copy (`KIOSK_VOICE_INSTRUCTIONS` in
  `backend/app/services/prompts/voice.py` is the only one).
- `kiosk-provider.tsx` waits for the session's own Spanish transcription, holds lone fragments
  briefly (`FRAGMENT_HOLD_MS`), sends the text to analysis or confirmation with a stable
  `turn_id`, and then requests one response with that turn's `SpeechPlan` data. A filler
  ("Un momento, por favor") is spoken if the bank takes longer than `FILLER_DELAY_MS`.
- A single response arbiter serializes everything spoken and drops responses whose business
  state is stale (`superseded`, `noop`, `settled` results are silent — see
  `turnResultIsSilent`).
- `microphoneShouldBeOpen` closes the mic only during protected identification, after a
  handoff/terminal result, and after a terminal decline.
- `kioskRouteForState` maps business state to the kiosk page.
- Session-state conflicts from the backend (`INVALID_SESSION_STATE`, …) are reconciled
  silently, not reported to the customer.
- Kiosk state persists in `sessionStorage` so a reload resumes; masked conversation history
  is re-fetched and merged by Realtime item ID.

## Running and testing

From `frontend/` (one surface at a time when sharing the local `.next` directory; use Docker
Compose to run both). `next.config.ts` loads the repository's root `.env`, which supplies
`BACKEND_INTERNAL_URL`; anything set on the command line, such as `APP_SURFACE`, wins over it:

```bash
APP_SURFACE=kiosk pnpm dev
PORT=3001 APP_SURFACE=staff pnpm dev
```

Tests live in `frontend/tests/` as `<feature>.test.ts(x)`, tagged with a `// @module-tag <category>`
header (`unit`, `functional`, `integration`, `regression`, `usability`). Root targets:
`make frontend-test`, `make frontend-lint`, `make frontend-typecheck`, `make frontend-build`.
See [Testing](testing.md).
