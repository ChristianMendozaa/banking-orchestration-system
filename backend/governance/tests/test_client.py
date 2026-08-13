import pytest
from pytest_httpx import HTTPXMock

from crew.client import BackendClient, BackendClientError

BASE_URL = "http://backend.test"


def test_login_stores_access_token(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/auth/login",
        json={"access_token": "token-123", "expires_in": 1800, "user": {}},
    )
    with BackendClient(BASE_URL) as client:
        client.login("gerencia@bmsc.com.bo", "secret")
        assert client.access_token == "token-123"


def test_login_failure_raises(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/auth/login", status_code=401, text="invalid credentials"
    )
    with BackendClient(BASE_URL) as client, pytest.raises(BackendClientError):
        client.login("gerencia@bmsc.com.bo", "wrong")


def test_access_token_before_login_raises() -> None:
    with BackendClient(BASE_URL) as client, pytest.raises(BackendClientError):
        _ = client.access_token


def test_download_document_sends_bearer_token(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/auth/login", json={"access_token": "token-123", "user": {}}
    )
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/management/knowledge/documents/doc-1/download",
        content=b"%PDF-1.4 fake",
        match_headers={"Authorization": "Bearer token-123"},
    )
    with BackendClient(BASE_URL) as client:
        client.login("gerencia@bmsc.com.bo", "secret")
        content = client.download_document("doc-1")
    assert content == b"%PDF-1.4 fake"


def test_submit_governance_proposal_posts_payload(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/auth/login", json={"access_token": "token-123", "user": {}}
    )
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/management/knowledge/documents/doc-1/governance-proposals",
        method="POST",
        status_code=201,
        json={"id": "proposal-1", "document_id": "doc-1"},
        match_headers={"Authorization": "Bearer token-123"},
    )
    with BackendClient(BASE_URL) as client:
        client.login("gerencia@bmsc.com.bo", "secret")
        result = client.submit_governance_proposal("doc-1", {"overall_recommendation": "ok"})
    assert result == {"id": "proposal-1", "document_id": "doc-1"}


def test_submit_governance_proposal_failure_raises(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/auth/login", json={"access_token": "token-123", "user": {}}
    )
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/management/knowledge/documents/doc-1/governance-proposals",
        method="POST",
        status_code=422,
        text="validation error",
    )
    with BackendClient(BASE_URL) as client, pytest.raises(BackendClientError):
        client.login("gerencia@bmsc.com.bo", "secret")
        client.submit_governance_proposal("doc-1", {})
