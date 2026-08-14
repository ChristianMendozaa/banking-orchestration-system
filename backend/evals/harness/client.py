"""Async REST client for the kiosk API.

Talks to a live backend exactly like the real kiosk frontend does -- no auth beyond the
per-session opaque token `POST /kiosk/sessions` issues. No dependency on `backend/app`.

Two access styles coexist on purpose:

- The named methods (`send_turn`, `send_confirmation`, ...) raise `KioskClientError` on
  any 4xx/5xx. They back the persona-driven scenarios, where an unexpected error really
  is a failure of the run.
- `request_raw` returns the status code and body without raising. It backs the `protocol`
  scenario group, whose whole point is asserting *which* 409 the backend returns.

`create_session` is the only call the backend rate-limits (30/min per client IP, see
`app/main.py`), and a concurrent 30-scenario run brushes against that ceiling, so it is
the only call that retries on 429.
"""

import asyncio
from dataclasses import dataclass
from uuid import uuid4

import httpx

CREATE_SESSION_ATTEMPTS = 5


class KioskClientError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SessionHandle:
    session_id: str
    session_token: str


@dataclass(frozen=True, slots=True)
class RawResponse:
    status_code: int
    body: dict | None
    text: str

    @property
    def code(self) -> str | None:
        """The backend's machine-readable error code (`AppError.code`), when this is an
        error envelope -- what the protocol scenarios actually assert on."""
        return self.body.get("code") if isinstance(self.body, dict) else None


class KioskClient:
    def __init__(self, base_url: str, *, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    async def create_session(self, *, preferential_attention: bool = False) -> SessionHandle:
        for attempt in range(CREATE_SESSION_ATTEMPTS):
            response = await self._client.post(
                "/api/v1/kiosk/sessions", json={"preferential_attention": preferential_attention}
            )
            if response.status_code != 429:
                break
            retry_after = float(response.headers.get("Retry-After", "2"))
            await asyncio.sleep(min(retry_after, 30) * (attempt + 1))
        self._raise_if_error(response, "create_session")
        body = response.json()
        return SessionHandle(session_id=body["session_id"], session_token=body["session_token"])

    async def send_turn(
        self,
        session: SessionHandle,
        transcript: str,
        *,
        is_clarification: bool,
        turn_id: str | None = None,
    ) -> dict:
        """`turn_id` is normally generated per call; the protocol scenarios pass an
        explicit one to replay the exact same turn twice."""
        response = await self._client.post(
            f"/api/v1/kiosk/sessions/{session.session_id}/turns",
            headers=self._headers(session),
            json={
                "turn_id": turn_id or str(uuid4()),
                "transcript": transcript,
                "is_clarification": is_clarification,
            },
        )
        self._raise_if_error(response, "send_turn")
        return response.json()

    async def send_confirmation(
        self, session: SessionHandle, requirement_id: str, confirmed: bool
    ) -> dict:
        response = await self._client.post(
            f"/api/v1/kiosk/sessions/{session.session_id}/confirmation",
            headers=self._headers(session),
            json={"requirement_id": requirement_id, "confirmed": confirmed},
        )
        self._raise_if_error(response, "send_confirmation")
        return response.json()

    async def send_identification(self, session: SessionHandle, identifier: str) -> dict:
        response = await self._client.post(
            f"/api/v1/kiosk/sessions/{session.session_id}/identification",
            headers=self._headers(session),
            json={"identifier": identifier},
        )
        self._raise_if_error(response, "send_identification")
        return response.json()

    async def get_status(self, session: SessionHandle) -> dict:
        response = await self._client.get(
            f"/api/v1/kiosk/sessions/{session.session_id}",
            headers=self._headers(session),
        )
        self._raise_if_error(response, "get_status")
        return response.json()

    async def request_raw(
        self,
        method: str,
        path: str,
        *,
        session: SessionHandle | None = None,
        json: dict | None = None,
    ) -> RawResponse:
        """Issue a request and report the outcome instead of raising.

        Used by the `protocol` scenarios, which assert on specific 409/422 codes -- an
        error there is the expected result, not a failure.
        """
        response = await self._client.request(
            method,
            path,
            headers=self._headers(session) if session else None,
            json=json,
        )
        try:
            body = response.json()
        except ValueError:
            body = None
        return RawResponse(status_code=response.status_code, body=body, text=response.text)

    @staticmethod
    def _headers(session: SessionHandle) -> dict[str, str]:
        return {"X-Session-Token": session.session_token}

    @staticmethod
    def _raise_if_error(response: httpx.Response, operation: str) -> None:
        if response.status_code >= 400:
            raise KioskClientError(f"{operation} failed: {response.status_code} {response.text}")

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "KioskClient":
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()
