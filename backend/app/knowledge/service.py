import hashlib
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.text import strip_internal_identifiers
from app.db.models import RAGInteraction
from app.domain.enums import Category
from app.domain.schemas import GroundedResponse
from app.knowledge.repository import KnowledgeRepository
from app.services.openai_provider import OpenAIProvider

PROMPT_VERSION = "rag-v1"
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
    ) -> GroundedResponse | None:
        if not self.provider:
            await self._log(db, case_id, masked_query, "PROVIDER_UNAVAILABLE", [], None)
            return None
        try:
            query_embedding = await self.provider.embedding(masked_query)
            chunks = await self.repository.retrieve(
                db,
                query_embedding=query_embedding,
                category=category,
                top_k=self.settings.rag_top_k,
                min_score=self.settings.rag_min_score,
            )
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
                    min_score=self.settings.rag_min_score,
                )
                await self._log(db, case_id, masked_query, "NO_EVIDENCE", retrieved, None)
                return None
            decision = await self.provider.grounded_answer(
                masked_query, chunks, branch_name=self.settings.branch_name
            )
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
            answer = strip_internal_identifiers(decision.answer)
            await self._log(db, case_id, masked_query, "GROUNDED", retrieved, answer)
            return GroundedResponse(answer=answer, citations=citations)
        except Exception as exc:
            logger.warning(
                "rag_provider_error",
                case_id=str(case_id) if case_id else None,
                error_type=type(exc).__name__,
            )
            await self._log(db, case_id, masked_query, "PROVIDER_ERROR", [], None)
            return None

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
