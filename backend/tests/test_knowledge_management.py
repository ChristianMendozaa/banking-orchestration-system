from io import BytesIO
from uuid import UUID

import pytest
from httpx import AsyncClient
from reportlab.pdfgen import canvas
from sqlalchemy import event

from app.api.deps import get_openai_provider
from app.db.models import KnowledgeDocument, KnowledgeJob
from app.domain.enums import KnowledgeIndexStatus, KnowledgeJobStatus
from app.knowledge import worker as worker_module
from app.knowledge.management import KnowledgeManagementService
from app.knowledge.worker import KnowledgeWorker
from app.main import app
from tests.conftest import TestSession, engine, fake_provider, settings_for_tests


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
            "email": "gerencia@bmsc.com.bo",
            "password": settings_for_tests.seed_manager_password.get_secret_value(),
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def process_job(worker: KnowledgeWorker, job_id: str) -> None:
    claimed = await worker.claim()
    assert str(claimed) == job_id
    assert claimed
    await worker.process(claimed)


async def test_manager_can_manage_document_lifecycle(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.dependency_overrides[get_openai_provider] = lambda: fake_provider
    monkeypatch.setattr(worker_module, "SessionFactory", TestSession)
    worker = KnowledgeWorker()
    worker.service = KnowledgeManagementService(settings_for_tests, fake_provider)
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
        assert created.status_code == 202, created.text
        first = created.json()
        first_id = first["document"]["id"]
        assert first["job"]["status"] == "QUEUED"
        assert first["document"]["index_status"] == "PENDING"
        assert first["document"]["active"] is False
        await process_job(worker, first["job"]["id"])
        completed = await client.get(
            f"/api/v1/management/knowledge/documents/jobs/{first['job']['id']}",
            headers=headers,
        )
        assert completed.json()["job"]["status"] == "SUCCEEDED"
        assert completed.json()["document"]["chunk_count"] > 0

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
        assert versioned.status_code == 202, versioned.text
        version_job = versioned.json()
        second_id = version_job["document"]["id"]
        assert second_id != first_id
        await process_job(worker, version_job["job"]["id"])

        first_after = await client.get(
            f"/api/v1/management/knowledge/documents/{first_id}",
            headers=headers,
        )
        assert first_after.json()["active"] is False

        reindexed = await client.post(
            f"/api/v1/management/knowledge/documents/{second_id}/reindex",
            headers=headers,
        )
        assert reindexed.status_code == 202, reindexed.text
        await process_job(worker, reindexed.json()["job"]["id"])
        reindexed_status = await client.get(
            f"/api/v1/management/knowledge/documents/jobs/{reindexed.json()['job']['id']}",
            headers=headers,
        )
        assert reindexed_status.json()["document"]["chunk_count"] > 0

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
                "email": "maria.fernandez@bmsc.com.bo",
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


async def test_document_listing_uses_constant_query_count(client: AsyncClient) -> None:
    headers = await manager_headers(client)
    statements = 0

    def count_statement(*_args) -> None:
        nonlocal statements
        statements += 1

    event.listen(engine.sync_engine, "before_cursor_execute", count_statement)
    try:
        response = await client.get(
            "/api/v1/management/knowledge/documents?page_size=100",
            headers=headers,
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_statement)

    assert response.status_code == 200
    assert response.json()["items"][0]["chunk_count"] == 1
    assert statements == 3  # usuario autenticado, total y página con conteos agregados


async def test_failed_knowledge_job_can_be_retried_with_a_limit(
    client: AsyncClient,
) -> None:
    headers = await manager_headers(client)
    created = await client.post(
        "/api/v1/management/knowledge/documents",
        headers=headers,
        files={
            "file": (
                "retry.pdf",
                pdf_bytes("Contenido documental para comprobar reintentos."),
                "application/pdf",
            )
        },
        data={
            "slug": "documento-reintento",
            "title": "Documento para reintento",
            "version": "1",
            "source_type": "INTERNAL",
            "categories": '["CONSULTA_GENERAL"]',
            "verified_at": "2026-07-16T12:00:00-04:00",
        },
    )
    payload = created.json()
    blocked_archive = await client.delete(
        f"/api/v1/management/knowledge/documents/{payload['document']['id']}",
        headers=headers,
    )
    assert blocked_archive.status_code == 409
    assert blocked_archive.json()["code"] == "KNOWLEDGE_JOB_ACTIVE"
    async with TestSession() as db:
        job = await db.get(KnowledgeJob, UUID(payload["job"]["id"]))
        document = await db.get(KnowledgeDocument, UUID(payload["document"]["id"]))
        assert job and document
        job.status = KnowledgeJobStatus.FAILED
        job.attempts = 1
        job.error_code = "TEST_FAILURE"
        job.error_message = "Fallo recuperable"
        document.index_status = KnowledgeIndexStatus.FAILED
        await db.commit()

    retried = await client.post(
        f"/api/v1/management/knowledge/documents/jobs/{payload['job']['id']}/retry",
        headers=headers,
    )
    assert retried.status_code == 202, retried.text
    assert retried.json()["job"]["status"] == "QUEUED"
    invalid_state = await client.post(
        f"/api/v1/management/knowledge/documents/jobs/{payload['job']['id']}/retry",
        headers=headers,
    )
    assert invalid_state.status_code == 409
    assert invalid_state.json()["code"] == "KNOWLEDGE_JOB_NOT_FAILED"

    async with TestSession() as db:
        job = await db.get(KnowledgeJob, UUID(payload["job"]["id"]))
        assert job
        job.status = KnowledgeJobStatus.FAILED
        job.attempts = job.max_attempts
        await db.commit()
    exhausted = await client.post(
        f"/api/v1/management/knowledge/documents/jobs/{payload['job']['id']}/retry",
        headers=headers,
    )
    assert exhausted.status_code == 409
    assert exhausted.json()["code"] == "KNOWLEDGE_JOB_EXHAUSTED"
