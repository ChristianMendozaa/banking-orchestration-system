from datetime import UTC, datetime
from uuid import uuid4

from httpx import AsyncClient

from app.db.models import KnowledgeDocument
from app.domain.enums import KnowledgeIndexStatus, KnowledgeSourceType
from tests.conftest import TestSession, settings_for_tests


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


async def executive_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "maria.fernandez@bmsc.com.bo",
            "password": settings_for_tests.seed_executive_password.get_secret_value(),
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _seed_document() -> KnowledgeDocument:
    async with TestSession() as db:
        document = KnowledgeDocument(
            slug=f"gobernanza-prueba-{uuid4().hex[:8]}",
            title="Documento de prueba de gobernanza",
            version="1",
            source_type=KnowledgeSourceType.INTERNAL,
            source_urls=[],
            verified_at=datetime(2026, 1, 1, tzinfo=UTC),
            review_after=None,
            file_name="documento.pdf",
            storage_key=f"{uuid4()}.pdf",
            mime_type="application/pdf",
            byte_size=100,
            page_count=1,
            content_sha256="c" * 64,
            metadata_json={"categories": ["CONSULTA_GENERAL"]},
            index_status=KnowledgeIndexStatus.READY,
            active=True,
        )
        db.add(document)
        await db.commit()
        await db.refresh(document)
        return document


def _payload(**overrides: object) -> dict:
    base = {
        "category_suggestions": ["CONSULTA_GENERAL", "CONSULTA_GENERAL", "BANCA_DIGITAL"],
        "section_suggestions": ["Horarios", "Canales digitales"],
        "review_after_suggestion": "2027-01-01T00:00:00Z",
        "compliance_veto": False,
        "compliance_flags": [],
        "compliance_notes": "Sin hallazgos sensibles.",
        "retrieval_qa_results": [
            {"question": "¿Cuál es el horario de atención?", "grounded": True, "notes": ""},
            {"question": "¿Cómo bloqueo mi tarjeta?", "grounded": False, "notes": "Sin evidencia"},
        ],
        "overall_recommendation": "Aprobar con ajuste de categorías.",
    }
    base.update(overrides)
    return base


async def test_manager_can_submit_and_list_governance_proposal(client: AsyncClient) -> None:
    document = await _seed_document()
    headers = await manager_headers(client)

    created = await client.post(
        f"/api/v1/management/knowledge/documents/{document.id}/governance-proposals",
        headers=headers,
        json=_payload(),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["document_id"] == str(document.id)
    assert body["category_suggestions"] == ["CONSULTA_GENERAL", "BANCA_DIGITAL"]
    assert body["compliance_veto"] is False
    assert len(body["retrieval_qa_results"]) == 2
    assert body["retrieval_qa_results"][1]["grounded"] is False

    listed = await client.get(
        f"/api/v1/management/knowledge/documents/{document.id}/governance-proposals",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == body["id"]


async def test_governance_proposal_never_mutates_the_document(client: AsyncClient) -> None:
    document = await _seed_document()
    headers = await manager_headers(client)

    await client.post(
        f"/api/v1/management/knowledge/documents/{document.id}/governance-proposals",
        headers=headers,
        json=_payload(compliance_veto=True, category_suggestions=["BANCA_DIGITAL"]),
    )

    unchanged = await client.get(
        f"/api/v1/management/knowledge/documents/{document.id}",
        headers=headers,
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["categories"] == ["CONSULTA_GENERAL"], (
        "a submitted proposal must never change the document -- a manager applies it "
        "manually via PATCH if they agree"
    )


async def test_unknown_document_is_rejected(client: AsyncClient) -> None:
    headers = await manager_headers(client)
    response = await client.post(
        f"/api/v1/management/knowledge/documents/{uuid4()}/governance-proposals",
        headers=headers,
        json=_payload(),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "KNOWLEDGE_DOCUMENT_NOT_FOUND"


async def test_executive_cannot_submit_governance_proposal(client: AsyncClient) -> None:
    document = await _seed_document()
    headers = await executive_headers(client)
    response = await client.post(
        f"/api/v1/management/knowledge/documents/{document.id}/governance-proposals",
        headers=headers,
        json=_payload(),
    )
    assert response.status_code == 403


async def test_proposals_listed_most_recent_first(client: AsyncClient) -> None:
    document = await _seed_document()
    headers = await manager_headers(client)
    first = await client.post(
        f"/api/v1/management/knowledge/documents/{document.id}/governance-proposals",
        headers=headers,
        json=_payload(overall_recommendation="Primera revisión"),
    )
    second = await client.post(
        f"/api/v1/management/knowledge/documents/{document.id}/governance-proposals",
        headers=headers,
        json=_payload(overall_recommendation="Segunda revisión"),
    )
    assert first.status_code == 201 and second.status_code == 201

    listed = await client.get(
        f"/api/v1/management/knowledge/documents/{document.id}/governance-proposals",
        headers=headers,
    )
    recommendations = [item["overall_recommendation"] for item in listed.json()]
    assert recommendations == ["Segunda revisión", "Primera revisión"]
