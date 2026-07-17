import hashlib
import json
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.db.models import RAGInteraction
from app.domain.enums import Category
from app.domain.schemas import GroundedAnswerDecision
from app.knowledge.chunking import chunk_pdf
from app.knowledge.ingestion import KnowledgeIngestionService
from app.knowledge.service import KnowledgeService
from tests.conftest import TestSession, fake_provider, settings_for_tests

CORPUS_DIR = Path(__file__).parents[2] / "doc" / "rag"


def test_generated_pdfs_are_searchable_and_split_by_section() -> None:
    manifest = json.loads((CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
    spec = manifest["documents"][0]
    chunks = chunk_pdf(
        CORPUS_DIR / spec["file_name"],
        model=settings_for_tests.embedding_model,
        chunk_tokens=settings_for_tests.rag_chunk_tokens,
        overlap_tokens=settings_for_tests.rag_chunk_overlap,
    )
    assert chunks
    assert "nueve departamentos" in " ".join(chunk.content for chunk in chunks)
    assert all(chunk.page == 1 for chunk in chunks)


def test_manifest_hashes_match_versioned_pdfs() -> None:
    manifest = json.loads((CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["documents"]) == 8
    for item in manifest["documents"]:
        digest = hashlib.sha256((CORPUS_DIR / item["file_name"]).read_bytes()).hexdigest()
        assert digest == item["sha256"]


async def test_ingestion_is_idempotent_and_backfills_skill_embeddings() -> None:
    manifest = json.loads((CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
    service = KnowledgeIngestionService(settings_for_tests, fake_provider)
    async with TestSession() as db:
        first = await service.ingest_corpus(db, CORPUS_DIR)
        second = await service.ingest_corpus(db, CORPUS_DIR)
    assert first["documents"] == len(manifest["documents"])
    assert first["chunks"] >= 8
    assert first["skills"] > 0
    assert second["documents"] == 0
    assert second["unchanged"] == len(manifest["documents"])
    assert second["skills"] == 0


async def test_no_semantic_evidence_is_logged_and_routes_to_human() -> None:
    service = KnowledgeService(settings_for_tests, fake_provider)
    async with TestSession() as db:
        answer = await service.answer(
            db,
            case_id=None,
            category=Category.CONSULTA_GENERAL,
            masked_query="pregunta completamente distinta",
        )
        await db.flush()
        interaction = await db.scalar(
            select(RAGInteraction).order_by(RAGInteraction.created_at.desc())
        )
    assert answer is None
    assert interaction is not None
    assert interaction.outcome == "NO_EVIDENCE"


async def test_model_cannot_cite_evidence_that_was_not_retrieved() -> None:
    class InvalidCitationProvider:
        async def embedding(self, text):
            return await fake_provider.embedding(text)

        async def grounded_answer(self, _query, _chunks):
            return GroundedAnswerDecision(
                answer="Respuesta no verificable",
                supported=True,
                cited_chunk_ids=[uuid4()],
            )

    service = KnowledgeService(settings_for_tests, InvalidCitationProvider())
    async with TestSession() as db:
        answer = await service.answer(
            db,
            case_id=None,
            category=Category.CONSULTA_GENERAL,
            masked_query="¿Cuál es el horario?",
        )
        await db.flush()
        interaction = await db.scalar(
            select(RAGInteraction).order_by(RAGInteraction.created_at.desc())
        )
    assert answer is None
    assert interaction is not None
    assert interaction.outcome == "INVALID_GROUNDING"
