import hashlib
from collections.abc import Callable, Sequence
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.metrics import GROUNDING_ATTEMPTS
from app.db.models import RAGInteraction
from app.domain.enums import Category, GroundingAttemptOutcome
from app.domain.schemas import GroundedResponse, GroundingAttempt
from app.knowledge.repository import KnowledgeRepository, RetrievedChunk
from app.services.openai_provider import OpenAIProvider

PROMPT_VERSION = "rag-v3-hybrid"
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
        answer_validator: Callable[[str], bool] | None = None,
    ) -> GroundingAttempt:
        queries = self._retrieval_queries(masked_query, retrieval_queries)
        base_diagnostics = {"queries": queries, "category": category.value}
        if not self.provider:
            return await self._finish(
                db,
                case_id,
                masked_query,
                GroundingAttemptOutcome.PROVIDER_UNAVAILABLE,
                [],
                base_diagnostics,
            )
        try:
            query_embeddings = await self.provider.embeddings(queries)
            chunks = await self._retrieve_merged(db, query_embeddings, queries, category)
            bounded_chunks: list[RetrievedChunk] = []
            context_tokens = 0
            for item in chunks:
                if context_tokens + item.chunk.token_count > self.settings.rag_max_context_tokens:
                    break
                bounded_chunks.append(item)
                context_tokens += item.chunk.token_count
            chunks = bounded_chunks
            retrieved = [self._retrieved_record(item) for item in chunks]
            diagnostics = {**base_diagnostics, "retrieved": retrieved}
            if not chunks:
                logger.warning(
                    "rag_no_candidates",
                    case_id=str(case_id) if case_id else None,
                    query=masked_query,
                    queries=queries,
                )
                return await self._finish(
                    db,
                    case_id,
                    masked_query,
                    GroundingAttemptOutcome.NO_CANDIDATES,
                    retrieved,
                    diagnostics,
                )

            decision = await self.provider.grounded_answer(masked_query, chunks)
            allowed = {index: item for index, item in enumerate(chunks, start=1)}
            cited = list(dict.fromkeys(decision.cited_evidence_refs))
            diagnostics["supported"] = decision.supported
            diagnostics["cited_evidence_refs"] = cited
            diagnostics["cited_chunk_ids"] = [
                str(allowed[ref].chunk.id) for ref in cited if ref in allowed
            ]
            if not decision.supported:
                return await self._finish(
                    db,
                    case_id,
                    masked_query,
                    GroundingAttemptOutcome.EVIDENCE_UNSUPPORTED,
                    retrieved,
                    diagnostics,
                )
            if not cited or any(ref not in allowed for ref in cited):
                return await self._finish(
                    db,
                    case_id,
                    masked_query,
                    GroundingAttemptOutcome.INVALID_CITATIONS,
                    retrieved,
                    diagnostics,
                )

            response = GroundedResponse(
                answer=decision.answer.strip(),
                citations=[allowed[ref].citation() for ref in cited],
            )
            if answer_validator and not answer_validator(response.answer):
                diagnostics["answer_language_rejected"] = True
                return await self._finish(
                    db,
                    case_id,
                    masked_query,
                    GroundingAttemptOutcome.ANSWER_LANGUAGE_REJECTED,
                    retrieved,
                    diagnostics,
                )
            return await self._finish(
                db,
                case_id,
                masked_query,
                GroundingAttemptOutcome.GROUNDED,
                retrieved,
                diagnostics,
                response=response,
            )
        except Exception as exc:
            logger.warning(
                "rag_provider_error",
                case_id=str(case_id) if case_id else None,
                error_type=type(exc).__name__,
            )
            return await self._finish(
                db,
                case_id,
                masked_query,
                GroundingAttemptOutcome.PROVIDER_ERROR,
                [],
                {**base_diagnostics, "error_type": type(exc).__name__},
            )

    @staticmethod
    def _retrieval_queries(masked_query: str, retrieval_queries: Sequence[str] | None) -> list[str]:
        candidates = list(retrieval_queries) if retrieval_queries else [masked_query]
        queries = list(dict.fromkeys(query.strip() for query in candidates if query.strip()))
        return queries or [masked_query]

    async def _retrieve_merged(
        self,
        db: AsyncSession,
        query_embeddings: list[list[float]],
        queries: list[str],
        category: Category,
    ) -> list[RetrievedChunk]:
        """Fuse semantic and lexical rankings without weakening the semantic threshold."""
        ranked_lists: list[tuple[str, list[RetrievedChunk]]] = []
        for query_embedding in query_embeddings:
            ranked_lists.append(
                (
                    "vector",
                    await self.repository.retrieve(
                        db,
                        query_embedding=query_embedding,
                        category=category,
                        top_k=self.settings.rag_top_k,
                        min_score=self.settings.rag_min_score,
                    ),
                )
            )
        for query in queries:
            ranked_lists.append(
                (
                    "lexical",
                    await self.repository.retrieve_lexical(
                        db, query=query, category=category, top_k=self.settings.rag_top_k
                    ),
                )
            )

        fused_scores: dict[UUID, float] = {}
        candidates: dict[UUID, RetrievedChunk] = {}
        channel_scores: dict[UUID, dict[str, float]] = {}
        for channel, ranked in ranked_lists:
            for rank, item in enumerate(ranked, start=1):
                fused_scores[item.chunk.id] = fused_scores.get(item.chunk.id, 0.0) + 1 / (60 + rank)
                candidates.setdefault(item.chunk.id, item)
                current_channel = channel_scores.setdefault(item.chunk.id, {})
                current_channel[channel] = max(
                    item.score, current_channel.get(channel, float("-inf"))
                )

        merged = []
        for chunk_id, item in candidates.items():
            channels = channel_scores[chunk_id]
            citation_score = channels.get("vector", channels.get("lexical", item.score))
            merged.append(
                RetrievedChunk(
                    chunk=item.chunk,
                    document=item.document,
                    score=citation_score,
                    channels={**channels, "fused": fused_scores[chunk_id]},
                )
            )
        merged.sort(key=lambda item: item.channels["fused"], reverse=True)
        return merged[: self.settings.rag_top_k]

    @staticmethod
    def _retrieved_record(item: RetrievedChunk) -> dict:
        return {
            "chunk_id": str(item.chunk.id),
            "document_id": str(item.document.id),
            "score": round(item.score, 6),
            "channels": {key: round(value, 6) for key, value in item.channels.items()},
            "page": item.chunk.page,
            "section": item.chunk.section,
        }

    async def _finish(
        self,
        db: AsyncSession,
        case_id: UUID | None,
        masked_query: str,
        outcome: GroundingAttemptOutcome,
        retrieved: list[dict],
        diagnostics: dict,
        response: GroundedResponse | None = None,
    ) -> GroundingAttempt:
        GROUNDING_ATTEMPTS.labels(outcome=outcome.value).inc()
        db.add(
            RAGInteraction(
                case_id=case_id,
                correlation_id=str(case_id) if case_id else None,
                masked_query=masked_query,
                outcome=outcome.value,
                model=self.settings.orchestration_model,
                prompt_version=PROMPT_VERSION,
                retrieved_json=retrieved,
                details_json=diagnostics,
                answer_sha256=(
                    hashlib.sha256(response.answer.encode()).hexdigest() if response else None
                ),
            )
        )
        return GroundingAttempt(outcome=outcome, response=response, diagnostics=diagnostics)
