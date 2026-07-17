import hashlib
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import RAGInteraction
from app.domain.enums import Category
from app.domain.schemas import GroundedResponse
from app.knowledge.repository import KnowledgeRepository
from app.services.openai_provider import OpenAIProvider

PROMPT_VERSION = "rag-v1"


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
                await self._log(db, case_id, masked_query, "INVALID_GROUNDING", retrieved, None)
                return None
            citations = [allowed[chunk_id].citation() for chunk_id in cited]
            await self._log(db, case_id, masked_query, "GROUNDED", retrieved, decision.answer)
            return GroundedResponse(answer=decision.answer.strip(), citations=citations)
        except Exception:
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
