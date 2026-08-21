from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.domain.enums import Category
from app.knowledge.chunking import TextChunk, chunk_pdf
from app.knowledge.repository import KnowledgeRepository
from app.services.openai_provider import OpenAIProvider


class NoIndexableTextError(ValueError):
    """The document did not produce any chunks suitable for indexing."""


class EmbeddingCountMismatchError(ValueError):
    """The provider returned an inconsistent number of vectors."""


def _embedding_text(document: KnowledgeDocument, chunk: TextChunk) -> str:
    header = " — ".join(part for part in (document.title, chunk.section) if part)
    return f"{header}\n\n{chunk.content}" if header else chunk.content


async def index_document(
    db: AsyncSession,
    *,
    document: KnowledgeDocument,
    path: Path,
    categories: list[Category],
    settings: Settings,
    provider: OpenAIProvider,
    repository: KnowledgeRepository,
    known_headings: set[str] | None = None,
) -> int:
    """Chunk, embed, and atomically replace a document's chunks."""
    text_chunks = chunk_pdf(
        path,
        model=settings.embedding_model,
        chunk_tokens=settings.rag_chunk_tokens,
        overlap_tokens=settings.rag_chunk_overlap,
        known_headings=known_headings,
    )
    if not text_chunks:
        raise NoIndexableTextError("El PDF no produjo fragmentos indexables")

    # Embed a contextual header, not the bare body. Measured against the live index before this
    # change: for "Quieres conocer los horarios de atencion", an unrelated card-blocking chunk
    # scored 0.516 and outranked the chunk whose own section heading is literally "¿En qué
    # horarios atienden las agencias?" (0.492). The heading is the strongest retrieval signal a
    # section has and it was being thrown away. `content` is stored unchanged, so citations and
    # the grounded-answer context see exactly what they saw before -- only the vector moves.
    embeddings = await provider.embeddings(
        [_embedding_text(document, chunk) for chunk in text_chunks]
    )
    if len(embeddings) != len(text_chunks):
        raise EmbeddingCountMismatchError(
            "La cantidad de embeddings no coincide con los fragmentos"
        )

    category_values = [category.value for category in categories]
    rows = [
        KnowledgeChunk(
            document_id=document.id,
            ordinal=chunk.ordinal,
            page=chunk.page,
            section=chunk.section,
            content=chunk.content,
            token_count=chunk.token_count,
            categories=category_values,
            content_sha256=chunk.content_sha256,
            embedding_model=settings.embedding_model,
            embedding=embedding,
        )
        for chunk, embedding in zip(text_chunks, embeddings, strict=True)
    ]
    await repository.replace_chunks(db, document, rows)
    await db.flush()
    return len(rows)
