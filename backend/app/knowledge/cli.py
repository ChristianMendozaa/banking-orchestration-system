import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.db.session import SessionFactory
from app.domain.enums import Category
from app.knowledge.ingestion import KnowledgeIngestionService
from app.knowledge.pdf_generator import generate_pdfs
from app.knowledge.repository import KnowledgeRepository
from app.services.openai_provider import OpenAIProvider


def _paths() -> tuple[Path, Path]:
    settings = get_settings()
    corpus = Path(settings.rag_corpus_dir).resolve()
    audit = corpus.parent / "auditoria_backend_arquitectura.pdf"
    return corpus, audit


def build_pdfs() -> None:
    corpus, audit = _paths()
    manifest = generate_pdfs(corpus, audit)
    print(
        json.dumps(
            {
                "corpus_dir": str(corpus),
                "audit": str(audit),
                "documents": len(manifest["documents"]),
            },
            ensure_ascii=False,
        )
    )


async def ingest() -> None:
    settings = get_settings()
    if not settings.openai_enabled:
        raise RuntimeError("OPENAI_API_KEY es obligatoria para generar embeddings")
    corpus, _ = _paths()
    service = KnowledgeIngestionService(settings, OpenAIProvider(settings))
    async with SessionFactory() as db:
        stats = await service.ingest_corpus(db, corpus)
    print(json.dumps(stats, ensure_ascii=False))


async def status() -> None:
    async with SessionFactory() as db:
        documents = await db.scalar(select(func.count(KnowledgeDocument.id))) or 0
        active = (
            await db.scalar(
                select(func.count(KnowledgeDocument.id)).where(KnowledgeDocument.active.is_(True))
            )
            or 0
        )
        chunks = await db.scalar(select(func.count(KnowledgeChunk.id))) or 0
    print(json.dumps({"documents": documents, "active": active, "chunks": chunks}))


async def evaluate() -> None:
    settings = get_settings()
    if not settings.openai_enabled:
        raise RuntimeError("OPENAI_API_KEY es obligatoria para evaluar retrieval")
    cases_path = Path(__file__).parents[2] / "tests" / "fixtures" / "rag_eval_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    provider = OpenAIProvider(settings)
    allowed = [case for case in cases if case["automatic_allowed"]]
    embeddings = await provider.embeddings([case["query"] for case in allowed])
    repository = KnowledgeRepository()
    failures = []
    async with SessionFactory() as db:
        for case, embedding in zip(allowed, embeddings, strict=True):
            chunks = await repository.retrieve(
                db,
                query_embedding=embedding,
                category=Category(case["category"]),
                top_k=settings.rag_top_k,
                min_score=settings.rag_min_score,
            )
            slugs = {item.document.slug for item in chunks}
            if case["expected_slug"] not in slugs:
                failures.append(
                    {
                        "query": case["query"],
                        "expected": case["expected_slug"],
                        "got": sorted(slugs),
                    }
                )
    passed = len(cases) - len(failures)
    result = {"total": len(cases), "passed": passed, "failed": len(failures), "failures": failures}
    print(json.dumps(result, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Base documental RAG del prototipo")
    parser.add_argument("command", choices=("build-pdfs", "ingest", "status", "evaluate"))
    args = parser.parse_args()
    if args.command == "build-pdfs":
        build_pdfs()
    elif args.command == "ingest":
        asyncio.run(ingest())
    elif args.command == "status":
        asyncio.run(status())
    else:
        asyncio.run(evaluate())


if __name__ == "__main__":
    main()
