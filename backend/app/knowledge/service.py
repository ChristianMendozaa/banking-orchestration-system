import hashlib
from collections.abc import Sequence
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import RAGInteraction
from app.domain.enums import Category
from app.domain.schemas import GroundedResponse
from app.knowledge.repository import KnowledgeRepository, RetrievedChunk
from app.services.openai_provider import OpenAIProvider

# Bumped from rag-v1 when retrieval went from one query per attempt to every phrasing
# searched together and merged. `rag_interactions` rows are how a grounding decision is
# reviewed after the fact, and rows produced by the two strategies are not comparable.
PROMPT_VERSION = "rag-v2"
logger = structlog.get_logger()


class KnowledgeService:
    def __init__(
        self,
        settings: Settings,
        provider: OpenAIProvider | None,
        repository: KnowledgeRepository | None = None,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.repository = repository or KnowledgeRepository()

    async def answer(
        self,
        db: AsyncSession,
        case_id: UUID | None,
        category: Category,
        masked_query: str,
        retrieval_queries: Sequence[str] | None = None,
    ) -> GroundedResponse | None:
        """Answers `masked_query` from the approved corpus, or returns None.

        `retrieval_queries` are the phrasings used to *search*; `masked_query` is the
        question the model is asked to answer. They are separate because the two want
        different strings: a summary written for the executive reading the case carries
        clauses that pull the retrieval vector off-target (see `finalize_nodes`), while the
        question itself must stay the one actually asked. Every variant is embedded in a
        single batched request and their hits are merged, so widening the search costs one
        round trip rather than one per phrasing -- which is what the sequential retry ladder
        this replaced used to cost, on exactly the public-information questions that should
        be the fastest thing the kiosk does.
        """
        queries = self._retrieval_queries(masked_query, retrieval_queries)
        if not self.provider:
            await self._log(db, case_id, masked_query, "PROVIDER_UNAVAILABLE", [], None)
            return None
        try:
            query_embeddings = await self.provider.embeddings(queries)
            chunks = await self._retrieve_merged(db, query_embeddings, category)
            bounded_chunks = []
            context_tokens = 0
            for item in chunks:
                if context_tokens + item.chunk.token_count > self.settings.rag_max_context_tokens:
                    break
                bounded_chunks.append(item)
                context_tokens += item.chunk.token_count
            chunks = bounded_chunks
            retrieved = [
                {
                    "chunk_id": str(item.chunk.id),
                    "document_id": str(item.document.id),
                    "score": round(item.score, 6),
                    "page": item.chunk.page,
                }
                for item in chunks
            ]
            if not chunks:
                # Only `rag_interactions` used to record this, and those rows cascade-delete
                # with the kiosk session -- so a general question that ended up at a human
                # window left nothing behind to explain why. Log it where it survives.
                logger.warning(
                    "rag_no_evidence",
                    case_id=str(case_id) if case_id else None,
                    category=category.value,
                    query=masked_query,
                    queries=queries,
                    min_score=self.settings.rag_min_score,
                )
                await self._log(db, case_id, masked_query, "NO_EVIDENCE", retrieved, None)
                return None
            decision = await self.provider.grounded_answer(masked_query, chunks)
            allowed = {item.chunk.id: item for item in chunks}
            cited = list(dict.fromkeys(decision.cited_chunk_ids))
            if (
                not decision.supported
                or not cited
                or any(chunk_id not in allowed for chunk_id in cited)
            ):
                logger.warning(
                    "rag_invalid_grounding",
                    case_id=str(case_id) if case_id else None,
                    category=category.value,
                    query=masked_query,
                    queries=queries,
                    supported=decision.supported,
                    cited_count=len(cited),
                    top_chunks=[
                        (item.document.slug, item.chunk.section, round(item.score, 4))
                        for item in chunks[:3]
                    ],
                )
                await self._log(db, case_id, masked_query, "INVALID_GROUNDING", retrieved, None)
                return None
            citations = [allowed[chunk_id].citation() for chunk_id in cited]
            await self._log(db, case_id, masked_query, "GROUNDED", retrieved, decision.answer)
            return GroundedResponse(answer=decision.answer.strip(), citations=citations)
        except Exception as exc:
            logger.warning(
                "rag_provider_error",
                case_id=str(case_id) if case_id else None,
                error_type=type(exc).__name__,
            )
            await self._log(db, case_id, masked_query, "PROVIDER_ERROR", [], None)
            return None

    @staticmethod
    def _retrieval_queries(masked_query: str, retrieval_queries: Sequence[str] | None) -> list[str]:
        """Deduplicated, non-empty search phrasings, always including something to search
        for. Order is preserved so the caller's primary phrasing stays first, which is what
        the merge below falls back to when two variants tie on score."""
        candidates = list(retrieval_queries) if retrieval_queries else [masked_query]
        queries = list(dict.fromkeys(query.strip() for query in candidates if query.strip()))
        return queries or [masked_query]

    async def _retrieve_merged(
        self,
        db: AsyncSession,
        query_embeddings: list[list[float]],
        category: Category,
    ) -> list[RetrievedChunk]:
        """Best `rag_top_k` chunks across every query variant, each chunk kept once at its
        highest score.

        Deliberately sequential: `retrieve` runs against a live `AsyncSession`, which is not
        safe to drive concurrently. That costs nothing worth optimising -- the expensive part
        of a retrieval round was the embedding call, and there is now exactly one of those no
        matter how many variants are searched. Trimming back to `rag_top_k` after the merge
        keeps the evidence block, and therefore the grounded-answer call, the same size it
        was with a single query.
        """
        best: dict[UUID, RetrievedChunk] = {}
        for query_embedding in query_embeddings:
            for item in await self.repository.retrieve(
                db,
                query_embedding=query_embedding,
                category=category,
                top_k=self.settings.rag_top_k,
                min_score=self.settings.rag_min_score,
            ):
                current = best.get(item.chunk.id)
                if current is None or item.score > current.score:
                    best[item.chunk.id] = item
        merged = sorted(best.values(), key=lambda item: item.score, reverse=True)
        return merged[: self.settings.rag_top_k]

    async def _log(
        self,
        db: AsyncSession,
        case_id: UUID | None,
        masked_query: str,
        outcome: str,
        retrieved: list[dict],
        answer: str | None,
    ) -> None:
        db.add(
            RAGInteraction(
                case_id=case_id,
                masked_query=masked_query,
                outcome=outcome,
                model=self.settings.orchestration_model,
                prompt_version=PROMPT_VERSION,
                retrieved_json=retrieved,
                answer_sha256=hashlib.sha256(answer.encode()).hexdigest() if answer else None,
            )
        )
