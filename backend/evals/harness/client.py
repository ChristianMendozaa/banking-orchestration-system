"""Async REST client for the kiosk API.

Talks to a live backend exactly like the real kiosk frontend does -- no auth beyond the
per-session opaque token `POST /kiosk/sessions` issues. No dependency on `backend/app`.
"""

from dataclasses import dataclass
from uuid import uuid4

import httpx


class KioskClientError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SessionHandle:
    session_id: str
    session_token: str


class KioskClient:
    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def create_session(self, *, preferential_attention: bool = False) -> SessionHandle:
        response = await self._client.post(
            "/api/v1/kiosk/sessions", json={"preferential_attention": preferential_attention}
        )
        self._raise_if_error(response, "create_session")
        body = response.json()
        return SessionHandle(session_id=body["session_id"], session_token=body["session_token"])

    async def send_turn(
        self, session: SessionHandle, transcript: str, *, is_clarification: bool
    ) -> dict:
        response = await self._client.post(
            f"/api/v1/kiosk/sessions/{session.session_id}/turns",
            headers=self._headers(session),
            json={
                "turn_id": str(uuid4()),
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
