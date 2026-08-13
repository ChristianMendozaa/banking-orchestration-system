"""Thin REST client for the backend's staff API.

The governance crew never touches the database or imports anything from `backend/app`
-- it authenticates and calls the API exactly like any other MANAGER-role client would.
"""

import httpx


class BackendClientError(RuntimeError):
    pass


class BackendClient:
    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self._base_url, timeout=timeout)
        self._access_token: str | None = None

    def login(self, email: str, password: str) -> None:
        response = self._client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        if response.status_code != 200:
            raise BackendClientError(f"login failed: {response.status_code} {response.text}")
        self._access_token = response.json()["access_token"]

    @property
    def access_token(self) -> str:
        """The same JWT used for REST calls; the MCP server validates it identically
        (same JWT_SECRET, same User/role model -- see app/mcp_server/auth.py), so it
        doubles as the MCP bearer token with no separate auth step."""
        if not self._access_token:
            raise BackendClientError("call login() before reading access_token")
        return self._access_token

    def _headers(self) -> dict[str, str]:
        if not self._access_token:
            raise BackendClientError("call login() before making authenticated requests")
        return {"Authorization": f"Bearer {self._access_token}"}

    def download_document(self, document_id: str) -> bytes:
        response = self._client.get(
            f"/api/v1/management/knowledge/documents/{document_id}/download",
            headers=self._headers(),
        )
        if response.status_code != 200:
            raise BackendClientError(
                f"download failed for {document_id}: {response.status_code} {response.text}"
            )
        return response.content

    def submit_governance_proposal(self, document_id: str, payload: dict) -> dict:
        response = self._client.post(
            f"/api/v1/management/knowledge/documents/{document_id}/governance-proposals",
            headers=self._headers(),
            json=payload,
        )
        if response.status_code != 201:
            raise BackendClientError(
                f"proposal submission failed for {document_id}: "
                f"{response.status_code} {response.text}"
            )
        return response.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BackendClient":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()
