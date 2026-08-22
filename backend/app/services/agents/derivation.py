"""The executive routing engine.

Ranks available executives for a case: `0.70 * semantic + 0.20 * experience +
0.10 * load`, ties broken by longest-idle then by id. `semantic` is the cosine
similarity between the case summary and the executive's skill description; when no
embedding provider is available it degrades to 1.0 so experience and load still decide.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Executive
from app.db.repositories import ExecutiveRepository
from app.domain.enums import Category
from app.services.openai_provider import OpenAIProvider

logger = structlog.get_logger()


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return numerator / denominator if denominator else 0.0


@dataclass(frozen=True, slots=True)
class DerivationDecision:
    executive: Executive
    score: float
    semantic_score: float
    experience_score: float
    load_score: float
    active_load: int


class DerivationAgent:
    def __init__(
        self,
        provider: OpenAIProvider | None,
        repository: ExecutiveRepository | None = None,
    ) -> None:
        self.provider = provider
        self.repository = repository or ExecutiveRepository()

    async def run(
        self, db: AsyncSession, category: Category, summary: str
    ) -> DerivationDecision | None:
        ranked = await self._rank(db, category, summary)
        return ranked[0][3] if ranked else None

    async def explain(
        self, db: AsyncSession, category: Category, summary: str
    ) -> list[DerivationDecision]:
        """Return every candidate's scoring breakdown, best first.

        Read-only replay of `run()`'s ranking for the `explain_routing_decision` MCP
        tool. Does not affect routing: `run()` still owns the actual assignment.
        """
        ranked = await self._rank(db, category, summary)
        return [row[3] for row in ranked]

    async def _rank(
        self, db: AsyncSession, category: Category, summary: str
    ) -> list[tuple[float, datetime, str, DerivationDecision]]:
        executives = await self.repository.available(db)
        if not executives:
            return []

        loads = await self.repository.active_loads(db)
        max_load = max([*loads.values(), 1])

        case_embedding: list[float] | None = None
        if self.provider:
            try:
                case_embedding = await self.provider.embedding(summary)
            except Exception as exc:
                logger.warning(
                    "routing_embedding_fallback",
                    error_type=type(exc).__name__,
                )
                case_embedding = None

        ranked: list[tuple[float, datetime, str, DerivationDecision]] = []
        for executive in executives:
            matching = [skill for skill in executive.skills if skill.category == category]
            if not matching:
                continue
            best_skill = max(matching, key=lambda skill: skill.experience_level)
            semantic = 1.0 if case_embedding is None else 0.0
            if case_embedding is not None:
                try:
                    if best_skill.embedding is None and self.provider:
                        best_skill.embedding = await self.provider.embedding(best_skill.description)
                    if best_skill.embedding is not None:
                        semantic = max(
                            0.0,
                            _cosine(case_embedding, list(best_skill.embedding)),
                        )
                except Exception as exc:
                    logger.warning(
                        "routing_skill_embedding_fallback",
                        executive_id=str(executive.id),
                        error_type=type(exc).__name__,
                    )
            experience = min(max(best_skill.experience_level, 1), 5) / 5
            load_score = 1 - (loads[executive.id] / max_load)
            score = 0.70 * semantic + 0.20 * experience + 0.10 * load_score
            idle = executive.last_assigned_at or datetime.min.replace(tzinfo=UTC)
            ranked.append(
                (
                    score,
                    idle,
                    str(executive.id),
                    DerivationDecision(
                        executive=executive,
                        score=score,
                        semantic_score=semantic,
                        experience_score=experience,
                        load_score=load_score,
                        active_load=loads[executive.id],
                    ),
                )
            )
        ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
        return ranked
