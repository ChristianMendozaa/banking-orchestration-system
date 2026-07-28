import math
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import cast, delete, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.domain.enums import Category
from app.domain.schemas import KnowledgeCitation


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: KnowledgeChunk
    document: KnowledgeDocument
    score: float

    def citation(self) -> KnowledgeCitation:
        return KnowledgeCitation(
            document_id=self.document.id,
            chunk_id=self.chunk.id,
            title=self.document.title,
            section=self.chunk.section,
            page=self.chunk.page,
            source_url=self.document.source_urls[0] if self.document.source_urls else None,
            score=max(-1.0, min(1.0, self.score)),
        )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return numerator / denominator if denominator else 0.0


class KnowledgeRepository:
    async def current_document(
        self, db: AsyncSession, slug: str, version: str
    ) -> KnowledgeDocument | None:
        return await db.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.slug == slug, KnowledgeDocument.version == version
            )
        )

    async def replace_chunks(
        self, db: AsyncSession, document: KnowledgeDocument, chunks: list[KnowledgeChunk]
    ) -> None:
        await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))
        db.add_all(chunks)

    async def deactivate_other_versions(self, db: AsyncSession, slug: str, active_id: UUID) -> None:
        documents = list(
            (
                await db.scalars(
                    select(KnowledgeDocument).where(
                        KnowledgeDocument.slug == slug,
                        KnowledgeDocument.id != active_id,
                        KnowledgeDocument.active.is_(True),
                    )
                )
            ).all()
        )
        for document in documents:
            document.active = False

    async def retrieve(
        self,
        db: AsyncSession,
        query_embedding: list[float],
        category: Category,
        top_k: int,
        min_score: float,
    ) -> list[RetrievedChunk]:
        now = datetime.now(UTC)
        dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
        base_filters = [KnowledgeDocument.active.is_(True)]
        candidates: list[RetrievedChunk] = []
        if dialect == "postgresql":
            distance = KnowledgeChunk.embedding.cosine_distance(query_embedding).label("distance")
            rows = (
                await db.execute(
                    select(KnowledgeChunk, KnowledgeDocument, distance)
                    .join(KnowledgeChunk.document)
                    .where(
                        *base_filters,
                        or_(
                            KnowledgeDocument.review_after.is_(None),
                            KnowledgeDocument.review_after >= now,
                        ),
                        or_(
                            cast(KnowledgeChunk.categories, JSONB) == [],
                            cast(KnowledgeChunk.categories, JSONB).contains([category.value]),
                        ),
                        distance <= 1 - min_score,
                    )
                    .order_by(distance)
                    .limit(top_k)
                )
            ).all()
            candidates = [
                RetrievedChunk(chunk=row[0], document=row[1], score=1 - float(row[2]))
                for row in rows
            ]
        else:
            rows = (
                await db.execute(
                    select(KnowledgeChunk, KnowledgeDocument)
                    .join(KnowledgeChunk.document)
                    .where(*base_filters)
                )
            ).all()
            candidates = [
                RetrievedChunk(
                    chunk=row[0],
                    document=row[1],
                    score=cosine_similarity(query_embedding, list(row[0].embedding)),
                )
                for row in rows
            ]
            candidates.sort(key=lambda item: item.score, reverse=True)

        selected = []
        for item in candidates:
            review_after = item.document.review_after
            if review_after and review_after.tzinfo is None:
                review_after = review_after.replace(tzinfo=UTC)
            if review_after and review_after < now:
                continue
            if item.chunk.categories and category.value not in item.chunk.categories:
                continue
            if item.score < min_score:
                continue
            selected.append(item)
            if len(selected) == top_k:
                break
        return selected
