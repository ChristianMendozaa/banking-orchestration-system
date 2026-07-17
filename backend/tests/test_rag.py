from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.db.models import RAGInteraction
from app.domain.enums import Category
from app.domain.schemas import GroundedAnswerDecision
from app.knowledge.chunking import chunk_pdf
from app.knowledge.corpus import CORPUS_DOCUMENTS
from app.knowledge.ingestion import KnowledgeIngestionService
from app.knowledge.pdf_generator import generate_pdfs
from app.knowledge.service import KnowledgeService
from tests.conftest import TestSession, fake_provider, settings_for_tests

CORPUS_DIR = Path(__file__).parents[2] / "doc" / "rag"


def test_generated_pdfs_are_searchable_and_split_by_section() -> None:
    spec = CORPUS_DOCUMENTS[0]
    chunks = chunk_pdf(
        CORPUS_DIR / spec.file_name,
        model=settings_for_tests.embedding_model,
        chunk_tokens=settings_for_tests.rag_chunk_tokens,
        overlap_tokens=settings_for_tests.rag_chunk_overlap,
        known_headings={heading for heading, _ in spec.sections},
    )
    assert len(chunks) == len(spec.sections)
    assert chunks[0].section == "Canales de atención"
    assert "nueve departamentos" in chunks[0].content
    assert all(chunk.page == 1 for chunk in chunks)


def test_pdf_generation_is_reproducible(tmp_path) -> None:
    corpus_dir = tmp_path / "rag"
    audit_path = tmp_path / "audit.pdf"
    first = generate_pdfs(corpus_dir, audit_path)
    first_hashes = {item["file_name"]: item["sha256"] for item in first["documents"]}
    first_audit = audit_path.read_bytes()
    second = generate_pdfs(corpus_dir, audit_path)
    second_hashes = {item["file_name"]: item["sha256"] for item in second["documents"]}
    assert first_hashes == second_hashes
    assert first_audit == audit_path.read_bytes()


async def test_ingestion_is_idempotent_and_backfills_skill_embeddings() -> None:
    service = KnowledgeIngestionService(settings_for_tests, fake_provider)
    async with TestSession() as db:
        first = await service.ingest_corpus(db, CORPUS_DIR)
        second = await service.ingest_corpus(db, CORPUS_DIR)
    assert first["documents"] == len(CORPUS_DOCUMENTS)
    assert first["chunks"] >= 32
    assert first["skills"] > 0
    assert second["documents"] == 0
    assert second["unchanged"] == len(CORPUS_DOCUMENTS)
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
