"""The first-attention agent: answer from the approved corpus, or decline to.

Bails out immediately for any consultation level other than GENERAL -- that is the only
level the kiosk may answer without identifying the person -- and rejects an otherwise
grounded answer whose wording would not read naturally at a kiosk.
"""

from collections.abc import Sequence
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import Category, ConsultationLevel
from app.domain.schemas import GroundedResponse
from app.knowledge.service import KnowledgeService
from app.services.agents.rules.language import grounded_answer_is_natural

logger = structlog.get_logger()


class InitialAttentionAgent:
    def __init__(self, knowledge: KnowledgeService) -> None:
        self.knowledge = knowledge

    async def run(
        self,
        db: AsyncSession,
        case_id: UUID,
        category: Category,
        level: ConsultationLevel,
        masked_query: str,
        retrieval_queries: Sequence[str] | None = None,
    ) -> GroundedResponse | None:
        """`masked_query` is the question to answer; `retrieval_queries` are the phrasings
        to search with, which the caller widens when the question's wording is known to be a
        poor search key (see `finalize_nodes.attempt_grounding`). Defaults to searching with
        the question itself."""
        if level != ConsultationLevel.GENERAL:
            return None
        response = await self.knowledge.answer(
            db, case_id, category, masked_query, retrieval_queries
        )
        if response and not grounded_answer_is_natural(response.answer):
            logger.warning("grounded_answer_rejected", case_id=str(case_id), category=category)
            return None
        return response
