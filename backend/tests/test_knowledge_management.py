from io import BytesIO

from httpx import AsyncClient
from reportlab.pdfgen import canvas

from app.api.deps import get_openai_provider
from app.main import app
from tests.conftest import fake_provider, settings_for_tests


def pdf_bytes(text: str) -> bytes:
    output = BytesIO()
    document = canvas.Canvas(output)
    document.drawString(72, 760, text)
    document.save()
    return output.getvalue()


async def manager_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "gerencia@personal.bmsc.com.bo",
            "password": settings_for_tests.seed_manager_password.get_secret_value(),
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_manager_can_manage_document_lifecycle(client: AsyncClient) -> None:
    app.dependency_overrides[get_openai_provider] = lambda: fake_provider
    try:
        headers = await manager_headers(client)
        created = await client.post(
            "/api/v1/management/knowledge/documents",
            headers=headers,
            files={
                "file": (
                    "manual-atencion.pdf",
                    pdf_bytes("El horario de plataforma se valida en canales oficiales."),
                    "application/pdf",
                )
            },
            data={
                "slug": "manual-atencion-prueba",
                "title": "Manual de atención de prueba",
                "version": "1.0",
                "source_type": "INTERNAL",
                "categories": '["CONSULTA_GENERAL"]',
                "source_urls": '["https://example.test/manual"]',
                "verified_at": "2026-07-16T12:00:00-04:00",
                "review_after": "2030-07-16T12:00:00-04:00",
            },
        )
        assert created.status_code == 201, created.text
        first = created.json()
        first_id = first["document"]["id"]
        assert first["indexed_chunks"] > 0
        assert first["document"]["index_status"] == "READY"
        assert first["document"]["active"] is True

        listed = await client.get(
            "/api/v1/management/knowledge/documents?search=manual-atencion-prueba",
            headers=headers,
        )
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        updated = await client.patch(
            f"/api/v1/management/knowledge/documents/{first_id}",
            headers=headers,
            json={
                "title": "Manual de atención actualizado",
                "categories": ["CONSULTA_GENERAL", "BANCA_DIGITAL"],
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["title"] == "Manual de atención actualizado"
        assert updated.json()["categories"] == ["CONSULTA_GENERAL", "BANCA_DIGITAL"]

        downloaded = await client.get(
            f"/api/v1/management/knowledge/documents/{first_id}/download",
            headers=headers,
        )
        assert downloaded.status_code == 200
        assert downloaded.content.startswith(b"%PDF-")

        versioned = await client.post(
            f"/api/v1/management/knowledge/documents/{first_id}/versions",
            headers=headers,
            files={
                "file": (
                    "manual-atencion-v2.pdf",
                    pdf_bytes("Nueva guía de banca digital y horarios de atención."),
                    "application/pdf",
                )
            },
            data={
                "version": "2.0",
                "verified_at": "2026-07-16T12:00:00-04:00",
                "review_after": "2030-07-16T12:00:00-04:00",
            },
        )
        assert versioned.status_code == 201, versioned.text
        second_id = versioned.json()["document"]["id"]
        assert second_id != first_id

        first_after = await client.get(
            f"/api/v1/management/knowledge/documents/{first_id}",
            headers=headers,
        )
        assert first_after.json()["active"] is False

        reindexed = await client.post(
            f"/api/v1/management/knowledge/documents/{second_id}/reindex",
            headers=headers,
        )
        assert reindexed.status_code == 200, reindexed.text
        assert reindexed.json()["indexed_chunks"] > 0

        archived = await client.delete(
            f"/api/v1/management/knowledge/documents/{second_id}",
            headers=headers,
        )
        assert archived.status_code == 204
        archived_detail = await client.get(
            f"/api/v1/management/knowledge/documents/{second_id}",
            headers=headers,
        )
        assert archived_detail.json()["index_status"] == "ARCHIVED"
        assert archived_detail.json()["active"] is False

        activated = await client.patch(
            f"/api/v1/management/knowledge/documents/{second_id}",
            headers=headers,
            json={"active": True},
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["index_status"] == "READY"
        assert activated.json()["active"] is True
    finally:
        app.dependency_overrides.pop(get_openai_provider, None)


async def test_knowledge_management_rejects_non_pdf_and_wrong_role(
    client: AsyncClient,
) -> None:
    app.dependency_overrides[get_openai_provider] = lambda: fake_provider
    try:
        headers = await manager_headers(client)
        invalid = await client.post(
            "/api/v1/management/knowledge/documents",
            headers=headers,
            files={"file": ("not-a-pdf.txt", b"plain text", "text/plain")},
            data={
                "slug": "archivo-invalido",
                "title": "Archivo inválido",
                "version": "1",
                "source_type": "INTERNAL",
                "categories": '["CONSULTA_GENERAL"]',
                "verified_at": "2026-07-16T12:00:00-04:00",
            },
        )
        assert invalid.status_code == 415
        assert invalid.json()["code"] == "INVALID_PDF"

        invalid_source = await client.post(
            "/api/v1/management/knowledge/documents",
            headers=headers,
            files={
                "file": (
                    "fuente-invalida.pdf",
                    pdf_bytes("Documento con fuente inválida."),
                    "application/pdf",
                )
            },
            data={
                "slug": "fuente-invalida",
                "title": "Fuente inválida",
                "version": "1",
                "source_type": "INTERNAL",
                "categories": '["CONSULTA_GENERAL"]',
                "source_urls": '["javascript:alert(1)"]',
                "verified_at": "2026-07-16T12:00:00-04:00",
            },
        )
        assert invalid_source.status_code == 422
        assert invalid_source.json()["code"] == "INVALID_SOURCE_URL"

        executive = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "maria.fernandez@personal.bmsc.com.bo",
                "password": settings_for_tests.seed_executive_password.get_secret_value(),
            },
        )
        executive_headers = {"Authorization": f"Bearer {executive.json()['access_token']}"}
        forbidden = await client.get(
            "/api/v1/management/knowledge/documents",
            headers=executive_headers,
        )
        assert forbidden.status_code == 403
    finally:
        app.dependency_overrides.pop(get_openai_provider, None)
