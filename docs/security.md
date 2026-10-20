# Security and privacy

The implementation applies defense-in-depth controls appropriate to the project scope:

- Raw audio is handled by the realtime channel and is not persisted by the application.
- Original audio and unmasked transcripts are not stored. Completed dialogue messages are masked again by the backend, retained for 90 configurable days, and then purged automatically.
- PINs, CVVs, passwords, credentials, and complete financial data are explicitly prohibited in realtime and grounded-answer instructions.
- Model calls leave the backend only with masked text: classification, confirmation reading, and grounded answers go to Anthropic (Claude Haiku 5.5); embeddings and realtime voice go to OpenAI.
- Neither the Anthropic key nor the regular OpenAI API key ever reaches the browser. The browser receives only a short-lived realtime client secret tied to the kiosk session.
- Kiosk access uses a high-entropy opaque token; only its SHA-256 hash is stored, and every protected kiosk route validates expiry.
- Customer identity-card numbers (CI) keep the HMAC-SHA-256 digest and masked suffix, plus an AES-256-GCM encrypted value protected by a versioned key. Only the assigned executive can reveal it, and every reveal is audited.
- Staff passwords use the recommended Argon2 password hash.
- Staff access uses short-lived HS256 JWTs. Opaque refresh tokens are stored as hashes, rotated on use, revocable, and delivered through `HttpOnly`, `SameSite=Lax` cookies (`Secure` in production).
- RBAC separates `EXECUTIVE` and `MANAGER`. Executives can access only their assigned tickets and reveal only those identifiers; managers receive masked, read-only case files, reporting, and knowledge-management permissions.
- Ticket transitions are allowlisted and guarded by optimistic concurrency. A partial unique constraint permits only one active attendance per executive, and closing requires a structured outcome and protected note.
- API errors share a stable contract with `code`, `message`, `details`, and `trace_id`; structured request logs include the same trace correlation header.
- Login, kiosk-session creation, and realtime-token creation have basic per-process rate limits.
- Application settings validate secret length, CORS origins, vector dimensions, retrieval limits, and mandatory AI configuration in production.
