import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import ExecutiveSkill, KnowledgeChunk, KnowledgeDocument
from app.domain.enums import Category, KnowledgeIndexStatus, KnowledgeSourceType
from app.knowledge.chunking import chunk_pdf
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
        storage_dir = Path(self.settings.knowledge_storage_dir).resolve()
        storage_dir.mkdir(parents=True, exist_ok=True)
        existing_files = {path.resolve() for path in storage_dir.iterdir() if path.is_file()}
        manifest_path = corpus_dir / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"No existe el manifiesto requerido: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        documents = manifest.get("documents")
        if not isinstance(documents, list):
            raise ValueError("El manifiesto no contiene una lista de documentos")
        try:
            for spec in documents:
                if not isinstance(spec, dict) or not isinstance(spec.get("file_name"), str):
                    raise ValueError("El manifiesto contiene un documento invalido")
                result = await self._ingest_document(db, corpus_dir / spec["file_name"], spec)
                if result is None:
                    stats["unchanged"] += 1
                else:
                    stats["documents"] += 1
                    stats["chunks"] += result
            stats["skills"] = await self._backfill_executive_skills(db)
            await db.commit()
        except Exception:
            await db.rollback()
            for stored_file in storage_dir.iterdir():
                if stored_file.is_file() and stored_file.resolve() not in existing_files:
                    stored_file.unlink(missing_ok=True)
            raise
        return stats

    async def _ingest_document(self, db: AsyncSession, path: Path, spec: dict) -> int | None:
        if not path.is_file():
            raise FileNotFoundError(f"No existe el PDF requerido: {path}")
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        slug = str(spec["slug"])
        version = str(spec["version"])
        document = await self.repository.current_document(db, slug, version)
        if document and document.content_sha256 == file_hash and document.active:
            storage_dir = Path(self.settings.knowledge_storage_dir).resolve()
            storage_dir.mkdir(parents=True, exist_ok=True)
            stored_path = storage_dir / document.storage_key
            if not stored_path.is_file():
                shutil.copy2(path, stored_path)
                document.byte_size = path.stat().st_size
                document.page_count = len(PdfReader(str(path)).pages)
                await db.flush()
            return None
        if document is not None:
            raise ValueError(f"El contenido de {slug}:{version} cambio sin incrementar la version")
        categories = [Category(value) for value in spec.get("categories", [])]
        if not categories:
            raise ValueError(f"El documento {slug} no declara categorias")
        verified_at = datetime.fromisoformat(str(spec["verified_at"]))
        review_after = (
            datetime.fromisoformat(str(spec["review_after"])) if spec.get("review_after") else None
        )
        storage_dir = Path(self.settings.knowledge_storage_dir).resolve()
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_key = f"{uuid4()}.pdf"
        stored_path = storage_dir / storage_key
        shutil.copy2(path, stored_path)
        page_count = len(PdfReader(str(path)).pages)
        document = KnowledgeDocument(
            slug=slug,
            title=str(spec["title"]),
            version=version,
            source_type=KnowledgeSourceType(str(spec["source_type"])),
            source_urls=list(spec.get("source_urls", [])),
            verified_at=verified_at,
            review_after=review_after,
            file_name=path.name,
            storage_key=storage_key,
            mime_type="application/pdf",
            byte_size=path.stat().st_size,
            page_count=page_count,
            content_sha256=file_hash,
            metadata_json={"categories": [category.value for category in categories]},
            index_status=KnowledgeIndexStatus.INDEXING,
            active=False,
        )
        db.add(document)
        await db.flush()

        text_chunks = chunk_pdf(
            path,
            model=self.settings.embedding_model,
            chunk_tokens=self.settings.rag_chunk_tokens,
            overlap_tokens=self.settings.rag_chunk_overlap,
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
                categories=[category.value for category in categories],
                content_sha256=chunk.content_sha256,
                embedding_model=self.settings.embedding_model,
                embedding=embedding,
            )
            for chunk, embedding in zip(text_chunks, embeddings, strict=True)
        ]
        await self.repository.replace_chunks(db, document, rows)
        await self.repository.deactivate_other_versions(db, slug, document.id)
        document.active = True
        document.index_status = KnowledgeIndexStatus.READY
        document.indexed_at = datetime.now(UTC)
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
