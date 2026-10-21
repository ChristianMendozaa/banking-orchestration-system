import hashlib
import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.models import KnowledgeDocument, RAGInteraction
from app.domain.enums import Category, GroundingAttemptOutcome, GroundingCoverage
from app.domain.schemas import GroundedAnswerDecision
from app.knowledge.chunking import chunk_pdf
from app.knowledge.ingestion import KnowledgeIngestionService
from app.knowledge.service import KnowledgeService
from app.services.agents.rules.language import grounded_answer_is_natural
from tests.conftest import TestSession, fake_provider, settings_for_tests

pytestmark = [pytest.mark.functional, pytest.mark.integration, pytest.mark.regression]

CORPUS_DIR = Path(__file__).parents[1] / "doc" / "rag"


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
    service = KnowledgeService(settings_for_tests, fake_provider, answerer=fake_provider)
    async with TestSession() as db:
        attempt = await service.answer(
            db,
            case_id=None,
            category=Category.CONSULTA_GENERAL,
            masked_query="pregunta completamente distinta",
        )
        await db.flush()
        interaction = await db.scalar(
            select(RAGInteraction).order_by(RAGInteraction.created_at.desc())
        )
    assert attempt.outcome is GroundingAttemptOutcome.NO_CANDIDATES
    assert attempt.response is None
    assert interaction is not None
    assert interaction.outcome == "NO_CANDIDATES"
    assert interaction.details_json["queries"] == ["pregunta completamente distinta"]


async def test_model_cannot_cite_evidence_that_was_not_retrieved() -> None:
    class InvalidCitationProvider:
        async def embeddings(self, texts):
            return await fake_provider.embeddings(texts)

        async def grounded_answer(self, _query, _chunks):
            return GroundedAnswerDecision(
                answer="Respuesta no verificable",
                spoken="Respuesta no verificable",
                coverage=GroundingCoverage.FULL,
                cited_evidence_refs=[999],
            )

    provider = InvalidCitationProvider()
    service = KnowledgeService(settings_for_tests, provider, answerer=provider)
    async with TestSession() as db:
        attempt = await service.answer(
            db,
            case_id=None,
            category=Category.CONSULTA_GENERAL,
            masked_query="¿Cuál es el horario?",
        )
        await db.flush()
        interaction = await db.scalar(
            select(RAGInteraction).order_by(RAGInteraction.created_at.desc())
        )
    assert attempt.outcome is GroundingAttemptOutcome.INVALID_CITATIONS
    assert interaction is not None
    assert interaction.outcome == "INVALID_CITATIONS"


class _ScriptedGrounder:
    """Returns the given decisions in order, recording any language feedback it was sent."""

    def __init__(self, *decisions: GroundedAnswerDecision) -> None:
        self.decisions = list(decisions)
        self.feedback: list[str | None] = []

    async def embeddings(self, texts):
        return await fake_provider.embeddings(texts)

    async def grounded_answer(self, _query, _chunks, *, language_feedback=None):
        self.feedback.append(language_feedback)
        return self.decisions.pop(0)


async def _ground(provider: _ScriptedGrounder):
    service = KnowledgeService(settings_for_tests, provider, answerer=provider)
    async with TestSession() as db:
        return await service.answer(
            db,
            case_id=None,
            category=Category.CONSULTA_GENERAL,
            masked_query="¿Cuál es el horario?",
            answer_validator=grounded_answer_is_natural,
        )


async def test_a_partial_answer_is_given_when_it_names_its_gap() -> None:
    """`requisitos_credito_general` (eval 2026-10-20): documents and income were in the
    evidence, the credit bureau was not, and a yes/no verdict threw the documented half away
    with the gap and sent a public question to a queue."""
    attempt = await _ground(
        _ScriptedGrounder(
            GroundedAnswerDecision(
                coverage=GroundingCoverage.PARTIAL,
                missing="el costo de reponer la tarjeta",
                cited_evidence_refs=[1],
                answer=(
                    "La línea gratuita atiende de lunes a sábado. Sobre el costo de reponer la "
                    "tarjeta no tengo información confirmada aquí; eso te lo confirma un "
                    "ejecutivo."
                ),
                spoken="La línea atiende de lunes a sábado; el costo te lo confirma un ejecutivo.",
            )
        )
    )
    assert attempt.outcome is GroundingAttemptOutcome.GROUNDED
    assert attempt.diagnostics["coverage"] == "PARTIAL"
    assert attempt.diagnostics["missing"] == "el costo de reponer la tarjeta"


@pytest.mark.parametrize(
    ("coverage", "missing"),
    [(GroundingCoverage.NONE, None), (GroundingCoverage.PARTIAL, None)],
)
async def test_no_coverage_or_an_unnamed_gap_is_not_an_answer(coverage, missing) -> None:
    attempt = await _ground(
        _ScriptedGrounder(
            GroundedAnswerDecision(
                coverage=coverage,
                missing=missing,
                cited_evidence_refs=[1],
                answer="Algo cercano a lo que se preguntó.",
                spoken="Algo cercano.",
            )
        )
    )
    assert attempt.outcome is GroundingAttemptOutcome.EVIDENCE_UNSUPPORTED
    assert attempt.response is None


def _decision(text: str) -> GroundedAnswerDecision:
    return GroundedAnswerDecision(
        coverage=GroundingCoverage.FULL, cited_evidence_refs=[1], answer=text, spoken=text
    )


async def test_an_answer_in_usted_is_rewritten_once_before_it_is_rejected() -> None:
    """`derechos_reclamo_asfi` (eval 2026-10-20): "Recuerde presentar primero el reclamo"
    -- the grounder copied the corpus's usted, which only the word "usted" used to catch."""
    provider = _ScriptedGrounder(
        _decision("Recuerde llamar a la línea gratuita."),
        _decision("Recuerda llamar a la línea gratuita."),
    )
    attempt = await _ground(provider)
    assert attempt.outcome is GroundingAttemptOutcome.GROUNDED
    assert attempt.response.answer == "Recuerda llamar a la línea gratuita."
    assert attempt.diagnostics["answer_language_retried"] is True
    assert provider.feedback[0] is None
    assert "de tú" in provider.feedback[1]

    stubborn = _ScriptedGrounder(
        _decision("Confirme antes de venir."), _decision("Confirme antes de venir.")
    )
    assert (await _ground(stubborn)).outcome is GroundingAttemptOutcome.ANSWER_LANGUAGE_REJECTED


async def test_model_evidence_references_are_resolved_to_real_chunk_ids() -> None:
    class AliasProvider:
        async def embeddings(self, texts):
            return await fake_provider.embeddings(texts)

        async def grounded_answer(self, _query, _chunks):
            return GroundedAnswerDecision(
                answer="Respuesta respaldada por dos fragmentos.",
                spoken="Respuesta respaldada por dos fragmentos.",
                coverage=GroundingCoverage.FULL,
                cited_evidence_refs=[1, 1],
            )

    provider = AliasProvider()
    service = KnowledgeService(settings_for_tests, provider, answerer=provider)
    async with TestSession() as db:
        attempt = await service.answer(
            db,
            case_id=None,
            category=Category.CONSULTA_GENERAL,
            masked_query="¿Cuál es el horario?",
        )

    assert attempt.outcome is GroundingAttemptOutcome.GROUNDED
    assert attempt.response is not None
    assert len(attempt.response.citations) == 1
    assert attempt.diagnostics["cited_evidence_refs"] == [1]
    assert attempt.diagnostics["cited_chunk_ids"] == [
        str(citation.chunk_id) for citation in attempt.response.citations
    ]


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
    service = KnowledgeService(settings_for_tests, provider, answerer=provider)
    vague = "Necesita ayuda con algo que todavia no describe"
    sharp = "Necesita el horario de atencion de la sucursal"

    async with TestSession() as db:
        # The vague phrasing on its own retrieves nothing: it is the NO_EVIDENCE the first
        # rung of the old ladder produced before any retry ran.
        first = await service.answer(
            db, case_id=None, category=Category.CONSULTA_GENERAL, masked_query=vague
        )
        assert first.outcome is GroundingAttemptOutcome.NO_CANDIDATES
        provider.embedding_calls.clear()
        provider.grounding_calls.clear()

        attempt = await service.answer(
            db,
            case_id=None,
            category=Category.CONSULTA_GENERAL,
            masked_query=vague,
            retrieval_queries=[vague, sharp],
        )

    assert attempt.outcome is GroundingAttemptOutcome.GROUNDED
    assert attempt.response is not None
    assert provider.embedding_calls == [[vague, sharp]]
    # The variants widen the *search*; the question asked stays the one that was asked.
    assert provider.grounding_calls == [vague]


async def test_hybrid_retrieval_recovers_ordinary_asr_spelling_noise() -> None:
    """Lexical retrieval must rescue a legible query even when its vector is unrelated."""

    class NoisyVectorProvider:
        async def embeddings(self, texts):
            return [[0.0, 1.0, *([0.0] * 1534)] for _ in texts]

        async def grounded_answer(self, query, chunks):
            return await fake_provider.grounded_answer(query, chunks)

    provider = NoisyVectorProvider()
    service = KnowledgeService(settings_for_tests, provider, answerer=provider)
    async with TestSession() as db:
        attempt = await service.answer(
            db,
            case_id=None,
            category=Category.CONSULTA_GENERAL,
            masked_query="cuales son los orarios de atencion de la sucursal",
        )

    assert attempt.outcome is GroundingAttemptOutcome.GROUNDED
    assert attempt.response is not None
    assert any("lexical" in item["channels"] for item in attempt.diagnostics["retrieved"])


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
    service = KnowledgeService(settings_for_tests, provider, answerer=provider)
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


@pytest.mark.parametrize(
    ("provider", "answerer"),
    [(fake_provider, None), (None, fake_provider)],
    ids=["no-orchestration-model", "no-embeddings"],
)
async def test_grounding_needs_both_the_embedder_and_the_answerer(provider, answerer) -> None:
    # Embeddings stay on OpenAI and the grounded answer moved to Claude, so the two keys can
    # be configured independently. Either one missing must route to a person, not crash
    # mid-turn on a None.
    service = KnowledgeService(settings_for_tests, provider, answerer=answerer)
    async with TestSession() as db:
        attempt = await service.answer(
            db,
            case_id=None,
            category=Category.CONSULTA_GENERAL,
            masked_query="¿cuál es el horario de atención?",
        )
    assert attempt.outcome == GroundingAttemptOutcome.PROVIDER_UNAVAILABLE
    assert attempt.response is None


def test_a_grounded_answer_over_its_length_is_cut_at_a_sentence_not_rejected() -> None:
    """Structured outputs do not enforce `max_length`; a few characters over the cap failed
    validation and discarded a grounded answer as PROVIDER_ERROR (2026-10-21)."""
    sentence = "Puedes abrir la cuenta en cualquier agencia con tu carnet vigente. "
    decision = GroundedAnswerDecision.model_validate(
        {
            "coverage": "FULL",
            "answer": sentence * 40,
            "spoken": sentence * 10,
            "cited_evidence_refs": [1],
        }
    )
    assert len(decision.answer) <= 1600
    assert decision.answer.endswith("vigente.")
    assert len(decision.spoken) <= 400
    assert decision.spoken.endswith("vigente.")


def test_cited_evidence_refs_are_required_in_the_grounding_schema() -> None:
    """With a default the field was optional in the JSON schema the model is constrained
    to, and FULL verdicts came back with no references (INVALID_CITATIONS, 2026-10-21)."""
    assert "cited_evidence_refs" in GroundedAnswerDecision.model_json_schema()["required"]
