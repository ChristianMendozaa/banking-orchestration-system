import pytest
from pytest_httpx import HTTPXMock

from harness.client import KioskClient, KioskClientError

BASE_URL = "http://kiosk.test"


async def test_create_session_returns_handle(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/kiosk/sessions",
        json={"session_id": "sid-1", "session_token": "tok-1", "status": "CREATED"},
    )
    async with KioskClient(BASE_URL) as client:
        handle = await client.create_session()
    assert handle.session_id == "sid-1"
    assert handle.session_token == "tok-1"


async def test_send_turn_includes_session_token_header(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/kiosk/sessions",
        json={"session_id": "sid-1", "session_token": "tok-1", "status": "CREATED"},
    )
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


async def test_error_response_raises(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=f"{BASE_URL}/api/v1/kiosk/sessions", status_code=500, text="boom")
    async with KioskClient(BASE_URL) as client:
        with pytest.raises(KioskClientError):
            await client.create_session()


async def test_get_status_hits_correct_path(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/kiosk/sessions",
        json={"session_id": "sid-1", "session_token": "tok-1", "status": "CREATED"},
    )
    httpx_mock.add_response(
        url=f"{BASE_URL}/api/v1/kiosk/sessions/sid-1",
        method="GET",
        json={"status": "ASSIGNED", "result": {}},
    )
    async with KioskClient(BASE_URL) as client:
        handle = await client.create_session()
        status = await client.get_status(handle)
    assert status["status"] == "ASSIGNED"
