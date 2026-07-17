import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import ExecutiveSkill, KnowledgeChunk, KnowledgeDocument
from app.knowledge.chunking import chunk_pdf
from app.knowledge.corpus import CORPUS_DOCUMENTS, CorpusDocument
from app.knowledge.repository import KnowledgeRepository
from app.services.openai_provider import OpenAIProvider


class KnowledgeIngestionService:
    def __init__(
        self,
        settings: Settings,
        provider: OpenAIProvider,
        repository: KnowledgeRepository | None = None,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.repository = repository or KnowledgeRepository()

    async def ingest_corpus(self, db: AsyncSession, corpus_dir: Path) -> dict[str, int]:
        stats = {"documents": 0, "chunks": 0, "unchanged": 0, "skills": 0}
        for spec in CORPUS_DOCUMENTS:
            result = await self._ingest_document(db, corpus_dir / spec.file_name, spec)
            if result is None:
                stats["unchanged"] += 1
            else:
                stats["documents"] += 1
                stats["chunks"] += result
        stats["skills"] = await self._backfill_executive_skills(db)
        await db.commit()
        return stats

    async def _ingest_document(
        self, db: AsyncSession, path: Path, spec: CorpusDocument
    ) -> int | None:
        if not path.is_file():
            raise FileNotFoundError(f"No existe el PDF requerido: {path}")
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        document = await self.repository.current_document(db, spec.slug, spec.version)
        if document and document.content_sha256 == file_hash and document.active:
            return None
        if document is None:
            document = KnowledgeDocument(
                slug=spec.slug,
                title=spec.title,
                version=spec.version,
                source_type=spec.source_type,
                source_urls=list(spec.source_urls),
                verified_at=spec.verified_at,
                review_after=spec.review_after,
                file_name=spec.file_name,
                content_sha256=file_hash,
                metadata_json={"categories": [category.value for category in spec.categories]},
                active=True,
            )
            db.add(document)
            await db.flush()
        else:
            document.title = spec.title
            document.source_type = spec.source_type
            document.source_urls = list(spec.source_urls)
            document.verified_at = spec.verified_at
            document.review_after = spec.review_after
            document.file_name = spec.file_name
            document.content_sha256 = file_hash
            document.metadata_json = {
                "categories": [category.value for category in spec.categories]
            }
            document.active = True

        text_chunks = chunk_pdf(
            path,
            model=self.settings.embedding_model,
            chunk_tokens=self.settings.rag_chunk_tokens,
            overlap_tokens=self.settings.rag_chunk_overlap,
            known_headings={heading for heading, _ in spec.sections},
        )
        if not text_chunks:
            raise ValueError(f"El PDF no produjo texto indexable: {path}")
        embeddings = await self.provider.embeddings([chunk.content for chunk in text_chunks])
        if len(embeddings) != len(text_chunks):
            raise ValueError("La API devolvio una cantidad inesperada de embeddings")
        rows = [
            KnowledgeChunk(
                document_id=document.id,
                ordinal=chunk.ordinal,
                page=chunk.page,
                section=chunk.section,
                content=chunk.content,
                token_count=chunk.token_count,
                categories=[category.value for category in spec.categories],
                content_sha256=chunk.content_sha256,
                embedding_model=self.settings.embedding_model,
                embedding=embedding,
            )
            for chunk, embedding in zip(text_chunks, embeddings, strict=True)
        ]
        await self.repository.replace_chunks(db, document, rows)
        await self.repository.deactivate_other_versions(db, spec.slug, document.id)
        await db.flush()
        return len(rows)

    async def _backfill_executive_skills(self, db: AsyncSession) -> int:
        skills = list(
            (
                await db.scalars(select(ExecutiveSkill).where(ExecutiveSkill.embedding.is_(None)))
            ).all()
        )
        if not skills:
            return 0
        embeddings = await self.provider.embeddings([skill.description for skill in skills])
        for skill, embedding in zip(skills, embeddings, strict=True):
            skill.embedding = embedding
        return len(skills)
