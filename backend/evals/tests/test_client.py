import json

import pytest
from pytest_httpx import HTTPXMock

from harness.client import KioskClient, KioskClientError

BASE_URL = "http://kiosk.test"
SESSION_JSON = {"session_id": "sid-1", "session_token": "tok-1", "status": "CREATED"}


async def test_create_session_returns_handle(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE_URL}/api/v1/kiosk/sessions", json=SESSION_JSON)
    async with KioskClient(BASE_URL) as client:
        handle = await client.create_session()
    assert handle.session_id == "sid-1"
    assert handle.session_token == "tok-1"


async def test_send_turn_includes_session_token_header(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE_URL}/api/v1/kiosk/sessions", json=SESSION_JSON)
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/kiosk/sessions/sid-1/turns",
        method="POST",
        json={"next_action": "CONFIRM", "category": "CONSULTA_GENERAL"},
        match_headers={"X-Session-Token": "tok-1"},
    )
    async with KioskClient(BASE_URL) as client:
        handle = await client.create_session()
        result = await client.send_turn(handle, "hola", is_clarification=False)
    assert result["next_action"] == "CONFIRM"


async def test_an_explicit_turn_id_is_sent_verbatim(httpx_mock: HTTPXMock) -> None:
    """Replaying a turn needs the same id twice, which the protocol scenarios rely on."""
    httpx_mock.add_response(url=f"{BASE_URL}/api/v1/kiosk/sessions", json=SESSION_JSON)
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/kiosk/sessions/sid-1/turns", method="POST", json={}
    )
    async with KioskClient(BASE_URL) as client:
        handle = await client.create_session()
        await client.send_turn(handle, "hola", is_clarification=False, turn_id="fixed-id")
    request = httpx_mock.get_requests()[-1]
    assert json.loads(request.content)["turn_id"] == "fixed-id"


async def test_error_response_raises(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE_URL}/api/v1/kiosk/sessions", status_code=500, text="boom")
    async with KioskClient(BASE_URL) as client:
        with pytest.raises(KioskClientError):
            await client.create_session()


async def test_a_rate_limited_session_creation_is_retried(httpx_mock: HTTPXMock) -> None:
    """`POST /kiosk/sessions` is capped at 30/min per client IP, which a concurrent
    30-scenario run can brush against."""
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/kiosk/sessions",
        status_code=429,
        headers={"Retry-After": "0"},
        json={"code": "RATE_LIMITED"},
    )
    httpx_mock.add_response(url=f"{BASE_URL}/api/v1/kiosk/sessions", json=SESSION_JSON)
    async with KioskClient(BASE_URL) as client:
        handle = await client.create_session()
    assert handle.session_id == "sid-1"
    assert len(httpx_mock.get_requests()) == 2


async def test_request_raw_reports_errors_instead_of_raising(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE_URL}/api/v1/kiosk/sessions", json=SESSION_JSON)
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/kiosk/sessions/sid-1/identification",
        method="POST",
        status_code=409,
        json={"code": "INVALID_SESSION_STATE", "message": "La sesión no espera un CI"},
    )
    async with KioskClient(BASE_URL) as client:
        handle = await client.create_session()
        response = await client.request_raw(
            "POST",
            "/api/v1/kiosk/sessions/sid-1/identification",
            session=handle,
            json={"identifier": "6735666"},
        )
    assert response.status_code == 409
    assert response.code == "INVALID_SESSION_STATE"


async def test_request_raw_survives_a_non_json_body(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE_URL}/api/v1/kiosk/sessions", json=SESSION_JSON)
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/kiosk/sessions/sid-1", method="GET", status_code=502, text="gateway"
    )
    async with KioskClient(BASE_URL) as client:
        handle = await client.create_session()
        response = await client.request_raw("GET", "/api/v1/kiosk/sessions/sid-1", session=handle)
    assert response.body is None
    assert response.code is None
    assert response.text == "gateway"


async def test_get_status_hits_correct_path(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE_URL}/api/v1/kiosk/sessions", json=SESSION_JSON)
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/kiosk/sessions/sid-1",
        method="GET",
        json={"status": "ASSIGNED", "result": {}},
    )
    async with KioskClient(BASE_URL) as client:
        handle = await client.create_session()
        status = await client.get_status(handle)
    assert status["status"] == "ASSIGNED"
