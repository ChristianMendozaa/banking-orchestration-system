from httpx import AsyncClient

from app.main import app
from tests.conftest import settings_for_tests

EXPECTED_OPERATIONS = {
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/logout"),
    ("GET", "/api/v1/auth/me"),
    ("POST", "/api/v1/auth/refresh"),
    ("GET", "/api/v1/executive/tickets"),
    ("GET", "/api/v1/health/live"),
    ("GET", "/api/v1/health/ready"),
    ("POST", "/api/v1/kiosk/sessions"),
    ("GET", "/api/v1/kiosk/sessions/{session_id}"),
    ("POST", "/api/v1/kiosk/sessions/{session_id}/confirmation"),
    ("POST", "/api/v1/kiosk/sessions/{session_id}/conversation/messages"),
    ("POST", "/api/v1/kiosk/sessions/{session_id}/identification"),
    ("POST", "/api/v1/kiosk/sessions/{session_id}/realtime-token"),
    ("POST", "/api/v1/kiosk/sessions/{session_id}/turns"),
    ("GET", "/api/v1/management/cases"),
    ("GET", "/api/v1/management/knowledge/documents"),
    ("POST", "/api/v1/management/knowledge/documents"),
    ("GET", "/api/v1/management/knowledge/documents/{document_id}"),
    ("PATCH", "/api/v1/management/knowledge/documents/{document_id}"),
    ("DELETE", "/api/v1/management/knowledge/documents/{document_id}"),
    ("GET", "/api/v1/management/knowledge/documents/{document_id}/download"),
    ("POST", "/api/v1/management/knowledge/documents/{document_id}/reindex"),
    ("POST", "/api/v1/management/knowledge/documents/{document_id}/versions"),
    ("GET", "/api/v1/management/metrics"),
    ("GET", "/api/v1/system/public-config"),
    ("GET", "/api/v1/tickets/{ticket_id}"),
    ("POST", "/api/v1/tickets/{ticket_id}/identifier/reveal"),
    ("PATCH", "/api/v1/tickets/{ticket_id}/status"),
}


def test_openapi_operation_contract_is_stable() -> None:
    schema = app.openapi()
    operations = {
        (method.upper(), path)
        for path, path_item in schema["paths"].items()
        for method in path_item
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert operations == EXPECTED_OPERATIONS


async def _manager_session(client: AsyncClient) -> tuple[str, str]:
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "gerencia@bmsc.com.bo",
            "password": settings_for_tests.seed_manager_password.get_secret_value(),
        },
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"], login.json()["user"]["id"]


async def test_operational_and_session_endpoints_preserve_contract(client: AsyncClient) -> None:
    live = await client.get("/api/v1/health/live")
    ready = await client.get("/api/v1/health/ready")
    config = await client.get("/api/v1/system/public-config")

    assert live.json() == {"status": "ok"}
    assert ready.json() == {"status": "ready"}
    assert config.json() == {
        "app_name": settings_for_tests.app_name,
        "bank_name": settings_for_tests.bank_name,
        "branch_name": settings_for_tests.branch_name,
        "dashboard_refresh_ms": settings_for_tests.dashboard_refresh_ms,
    }
    assert all(response.headers.get("x-trace-id") for response in (live, ready, config))

    token, user_id = await _manager_session(client)
    headers = {"Authorization": f"Bearer {token}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    cases = await client.get("/api/v1/management/cases", headers=headers)
    assert me.status_code == 200
    assert me.json()["id"] == user_id
    assert cases.status_code == 200
    assert cases.json() == {"items": [], "page": 1, "page_size": 20, "total": 0}

    logout = await client.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    assert "orquestacion_refresh=" in logout.headers.get("set-cookie", "")
