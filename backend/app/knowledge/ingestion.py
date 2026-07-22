import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pypdf import PdfReader
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import ExecutiveSkill, KnowledgeChunk, KnowledgeDocument
from app.domain.enums import Category, KnowledgeIndexStatus, KnowledgeSourceType
from app.knowledge.indexing import index_document
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
        stats = {"documents": 0, "chunks": 0, "unchanged": 0, "skills": 0, "retired": 0}
        storage_dir = Path(self.settings.knowledge_storage_dir).resolve()
        storage_dir.mkdir(parents=True, exist_ok=True)
        existing_files = {path.resolve() for path in storage_dir.iterdir() if path.is_file()}
        retired_storage_keys: list[str] = []
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
            retired_storage_keys = await self._retire_replaced_corpus_versions(db, documents)
            stats["retired"] = len(retired_storage_keys)
            await db.commit()
        except Exception:
            await db.rollback()
            for stored_file in storage_dir.iterdir():
                if stored_file.is_file() and stored_file.resolve() not in existing_files:
                    stored_file.unlink(missing_ok=True)
            raise
        for storage_key in retired_storage_keys:
            stored_path = (storage_dir / storage_key).resolve()
            if stored_path.parent == storage_dir:
                stored_path.unlink(missing_ok=True)
        return stats

    async def _ingest_document(self, db: AsyncSession, path: Path, spec: dict) -> int | None:
        if not path.is_file():
            raise FileNotFoundError(f"No existe el PDF requerido: {path}")
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if file_hash != str(spec.get("sha256", "")):
            raise ValueError(f"El hash declarado no coincide con el PDF: {path}")
        slug = str(spec["slug"])
        version = str(spec["version"])
        categories = [Category(value) for value in spec.get("categories", [])]
        if not categories:
            raise ValueError(f"El documento {slug} no declara categorias")
        sections = [str(value).strip() for value in spec.get("sections", []) if str(value).strip()]
        index_signature = self._index_signature(categories, sections)
        metadata = {
            "categories": [category.value for category in categories],
            "sections": sections,
            "managed_by": "corpus_bootstrap",
            "index_signature": index_signature,
        }
        verified_at = datetime.fromisoformat(str(spec["verified_at"]))
        review_after = (
            datetime.fromisoformat(str(spec["review_after"])) if spec.get("review_after") else None
        )
        storage_dir = Path(self.settings.knowledge_storage_dir).resolve()
        storage_dir.mkdir(parents=True, exist_ok=True)
        page_count = len(PdfReader(str(path)).pages)

        document = await self.repository.current_document(db, slug, version)
        if document is not None:
            if document.content_sha256 != file_hash:
                raise ValueError(
                    f"El contenido de {slug}:{version} cambio sin incrementar la version"
                )
            previous_signature = document.metadata_json.get("index_signature")
            was_active = document.active
            document.title = str(spec["title"])
            document.source_type = KnowledgeSourceType(str(spec["source_type"]))
            document.source_urls = list(spec.get("source_urls", []))
            document.verified_at = verified_at
            document.review_after = review_after
            document.file_name = path.name
            document.byte_size = path.stat().st_size
            document.page_count = page_count
            document.metadata_json = metadata
            stored_path = storage_dir / document.storage_key
            if not stored_path.is_file():
                shutil.copy2(path, stored_path)
            if (
                previous_signature == index_signature
                and document.index_status == KnowledgeIndexStatus.READY
            ):
                if not was_active:
                    await self.repository.deactivate_other_versions(db, slug, document.id)
                    document.active = True
                    await db.flush()
                    return 0
                await db.flush()
                return None
            return await self._index_document(db, document, path, categories, sections)

        storage_key = f"{uuid4()}.pdf"
        stored_path = storage_dir / storage_key
        shutil.copy2(path, stored_path)
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
            metadata_json=metadata,
            index_status=KnowledgeIndexStatus.INDEXING,
            active=False,
        )
        db.add(document)
        await db.flush()
        return await self._index_document(db, document, path, categories, sections)

    def _index_signature(self, categories: list[Category], sections: list[str]) -> str:
        configuration = {
            "strategy": "declared-sections-v1",
            "embedding_model": self.settings.embedding_model,
            "chunk_tokens": self.settings.rag_chunk_tokens,
            "overlap_tokens": self.settings.rag_chunk_overlap,
            "categories": [category.value for category in categories],
            "sections": sections,
        }
        encoded = json.dumps(
            configuration,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    async def _index_document(
        self,
        db: AsyncSession,
        document: KnowledgeDocument,
        path: Path,
        categories: list[Category],
        sections: list[str],
    ) -> int:
        document.index_status = KnowledgeIndexStatus.INDEXING
        document.index_error = None
        await db.flush()
        count = await index_document(
            db,
            document=document,
            path=path,
            categories=categories,
            settings=self.settings,
            provider=self.provider,
            repository=self.repository,
            known_headings=set(sections),
        )
        await self.repository.deactivate_other_versions(db, document.slug, document.id)
        document.active = True
        document.index_status = KnowledgeIndexStatus.READY
        document.indexed_at = datetime.now(UTC)
        await db.flush()
        return count

    async def _retire_replaced_corpus_versions(
        self, db: AsyncSession, specifications: list[dict]
    ) -> list[str]:
        expected = {
            (str(specification["slug"]), str(specification["version"]))
            for specification in specifications
        }
        slugs = {slug for slug, _ in expected}
        documents = list(
            (
                await db.scalars(
                    select(KnowledgeDocument).where(
                        KnowledgeDocument.slug.in_(slugs),
                        KnowledgeDocument.created_by_user_id.is_(None),
                    )
                )
            ).all()
        )
        retired = [
            document for document in documents if (document.slug, document.version) not in expected
        ]
        if not retired:
            return []
        retired_ids = [document.id for document in retired]
        await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id.in_(retired_ids)))
        await db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id.in_(retired_ids)))
        return [document.storage_key for document in retired]

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
