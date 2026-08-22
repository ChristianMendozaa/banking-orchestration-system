import hashlib
import json
import shutil
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from app.db.models import KnowledgeDocument, RAGInteraction
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
        known_headings=set(spec["sections"]),
    )
    assert chunks
    assert "nueve departamentos" in " ".join(chunk.content for chunk in chunks)
    assert {chunk.section for chunk in chunks} >= {
        "Canales de atención",
        "Contact Center",
        "Atención en agencias",
    }
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
    assert second["retired"] == 0


async def test_ingestion_retires_replaced_managed_versions(tmp_path: Path) -> None:
    corpus = tmp_path / "rag"
    shutil.copytree(CORPUS_DIR, corpus)
    service = KnowledgeIngestionService(settings_for_tests, fake_provider)
    async with TestSession() as db:
        await service.ingest_corpus(db, corpus)
        manifest_path = corpus / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        slug = manifest["documents"][0]["slug"]
        manifest["documents"][0]["version"] = "2026.07.2"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = await service.ingest_corpus(db, corpus)
        versions = list(
            (
                await db.scalars(
                    select(KnowledgeDocument.version).where(KnowledgeDocument.slug == slug)
                )
            ).all()
        )
    assert result["retired"] == 1
    assert versions == ["2026.07.2"]


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
        async def embeddings(self, texts):
            return await fake_provider.embeddings(texts)

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


async def test_alternative_phrasings_are_searched_in_one_embedding_call() -> None:
    """The retry ladder this replaced paid a full embedding + retrieval + grounded-answer
    cycle per phrasing, inside the request a customer is waiting on. The phrasings were only
    ever alternative *search keys* for one question, so they now go out together: one batched
    embeddings call, one merged result set, one grounding call.

    Pinned on the case that used to need the ladder -- a question whose own wording retrieves
    nothing, rescued by a sharper variant -- because that is the path where collapsing the
    ladder could have silently lost an answer."""

    class CountingProvider:
        def __init__(self) -> None:
            self.embedding_calls: list[list[str]] = []
            self.grounding_calls: list[str] = []

        async def embeddings(self, texts: list[str]) -> list[list[float]]:
            self.embedding_calls.append(list(texts))
            return await fake_provider.embeddings(texts)

        async def grounded_answer(self, query: str, chunks):
            self.grounding_calls.append(query)
            return await fake_provider.grounded_answer(query, chunks)

    provider = CountingProvider()
    service = KnowledgeService(settings_for_tests, provider)
    vague = "Necesita ayuda con algo que todavia no describe"
    sharp = "Necesita el horario de atencion de la sucursal"

    async with TestSession() as db:
        # The vague phrasing on its own retrieves nothing: it is the NO_EVIDENCE the first
        # rung of the old ladder produced before any retry ran.
        assert (
            await service.answer(
                db, case_id=None, category=Category.CONSULTA_GENERAL, masked_query=vague
            )
            is None
        )
        provider.embedding_calls.clear()
        provider.grounding_calls.clear()

        answer = await service.answer(
            db,
            case_id=None,
            category=Category.CONSULTA_GENERAL,
            masked_query=vague,
            retrieval_queries=[vague, sharp],
        )

    assert answer is not None
    assert provider.embedding_calls == [[vague, sharp]]
    # The variants widen the *search*; the question asked stays the one that was asked.
    assert provider.grounding_calls == [vague]


async def test_retrieval_queries_are_deduplicated_and_default_to_the_question() -> None:
    """`attempt_grounding` builds the variants unconditionally, so the common single-need
    turn hands over the same string two or three times. Embedding a duplicate would be paid
    tokens for a vector we already have."""

    class CountingProvider:
        def __init__(self) -> None:
            self.embedding_calls: list[list[str]] = []

        async def embeddings(self, texts: list[str]) -> list[list[float]]:
            self.embedding_calls.append(list(texts))
            return await fake_provider.embeddings(texts)

        async def grounded_answer(self, query: str, chunks):
            return await fake_provider.grounded_answer(query, chunks)

    question = "Necesita el horario de atencion"
    provider = CountingProvider()
    service = KnowledgeService(settings_for_tests, provider)
    async with TestSession() as db:
        await service.answer(
            db,
            case_id=None,
            category=Category.CONSULTA_GENERAL,
            masked_query=question,
            retrieval_queries=[question, question, "  "],
        )
        await service.answer(
            db, case_id=None, category=Category.CONSULTA_GENERAL, masked_query=question
        )

    assert provider.embedding_calls == [[question], [question]]


def test_principal_need_splits_a_multi_need_summary() -> None:
    """The retrieval query and the executive's case summary are the same string, and they want
    different things from it.

    The classification prompt asks for a summary that names the principal need and then says
    which one is deferred. That trailing clause is exactly what an executive needs and pure
    noise for pgvector: on 2026-08-19 "Necesita el horario de atencion de la sucursal y deja
    pendiente un problema bancario aun no descrito" retrieved "¿Que hago si no reconozco un
    movimiento?" as its top chunk, grounding correctly failed, and a question about branch
    hours was handed to a person.
    """
    from app.services.graph.finalize_nodes import principal_need

    assert (
        principal_need(
            "Necesita el horario de atencion de la sucursal y deja pendiente un problema "
            "bancario aun no descrito."
        )
        == "Necesita el horario de atencion de la sucursal"
    )
    assert (
        principal_need(
            "Necesita resolver un problema con su tarjeta y, aparte, consultar los documentos "
            "para un crédito."
        )
        == "Necesita resolver un problema con su tarjeta"
    )


def test_principal_need_leaves_a_single_need_summary_alone() -> None:
    """A plain "y" joining two halves of one need must not be treated as a second need --
    only the connectives that introduce a deferred one."""
    from app.services.graph.finalize_nodes import principal_need

    assert principal_need("Necesita los horarios de atencion de la sucursal.") is None
    assert principal_need("Necesita saber los requisitos y documentos para abrir una cuenta.") is (
        None
    )
