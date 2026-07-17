from uuid import uuid4

from httpx import AsyncClient


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def test_sensitive_case_identification_assignment_and_dashboard(client: AsyncClient) -> None:
    created = await client.post("/api/v1/kiosk/sessions", json={})
    session_id = created.json()["session_id"]
    session_headers = {"X-Session-Token": created.json()["session_token"]}
    turn = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/turns",
        headers=session_headers,
        json={
            "turn_id": str(uuid4()),
            "transcript": "Tengo un movimiento no reconocido y creo que es fraude",
        },
    )
    assert turn.status_code == 200, turn.text
    assert turn.json()["category"] == "REPORTE_FRAUDE"

    confirmed = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/confirmation",
        headers=session_headers,
        json={"confirmed": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["next_action"] == "IDENTIFY"

    identified = await client.post(
        f"/api/v1/kiosk/sessions/{session_id}/identification",
        headers=session_headers,
        json={"identifier": "DEMO-1001"},
    )
    assert identified.status_code == 200, identified.text
    result = identified.json()
    assert result["identification_status"] == "IDENTIFICADO"
    assert result["resolution_type"] == "HUMAN"
    assert result["ticket"]["status"] == "PENDIENTE"
    assert result["executive"] is not None

    executive_email = {
        "Carlos Mamani": "carlos.mamani@demo.example",
        "Maria Fernandez": "maria.fernandez@demo.example",
    }[result["executive"]["name"]]
    executive_token = await _login(client, executive_email, "ChangeMe-Executive-2026")
    executive_headers = {"Authorization": f"Bearer {executive_token}"}
    listing = await client.get("/api/v1/executive/tickets", headers=executive_headers)
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 1

    ticket_id = result["ticket"]["id"]
    updated = await client.patch(
        f"/api/v1/tickets/{ticket_id}/status",
        headers=executive_headers,
        json={"status": "EN_ATENCION", "expected_version": 1},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "EN_ATENCION"
    assert updated.json()["version"] == 2

    manager_token = await _login(client, "gerencia@demo.example", "ChangeMe-Manager-2026")
    metrics = await client.get(
        "/api/v1/management/metrics",
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["total_cases"] == 1
    assert metrics.json()["critical_pending"] == 1


async def test_manager_cannot_update_ticket_as_executive(client: AsyncClient) -> None:
    manager_token = await _login(client, "gerencia@demo.example", "ChangeMe-Manager-2026")
    response = await client.get(
        "/api/v1/executive/tickets",
        headers={"Authorization": f"Bearer {manager_token}"},
    )
    assert response.status_code == 403


async def test_refresh_rotates_session_and_validation_uses_public_error_contract(
    client: AsyncClient,
) -> None:
    await _login(client, "gerencia@demo.example", "ChangeMe-Manager-2026")
    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["token_type"] == "bearer"

    invalid = await client.post(
        "/api/v1/auth/login", json={"email": "invalid", "password": "short"}
    )
    assert invalid.status_code == 422
    body = invalid.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert all("input" not in detail for detail in body["details"])
