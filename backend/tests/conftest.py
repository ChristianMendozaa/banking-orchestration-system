import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ["APP_ENV"] = "test"
os.environ["APP_NAME"] = "Sistema de Orquestacion de Pruebas"
os.environ["BANK_NAME"] = "Banco de Pruebas"
os.environ["BRANCH_NAME"] = "Sucursal de Pruebas"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["CORS_ORIGINS"] = "http://test"
os.environ["OPENAI_API_KEY"] = ""
os.environ["JWT_SECRET"] = "test-jwt-secret-with-more-than-thirty-two-characters"
os.environ["IDENTIFIER_PEPPER"] = "test-identifier-pepper-with-more-than-thirty-two-characters"
os.environ["SEED_EXECUTIVE_PASSWORD"] = "test-executive-password"
os.environ["SEED_MANAGER_PASSWORD"] = "test-manager-password"
os.environ["KNOWLEDGE_STORAGE_DIR"] = "/tmp/sistema-orquestacion-tests-knowledge"

from app.api.deps import get_orchestrator  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import KnowledgeChunk, KnowledgeDocument  # noqa: E402
from app.db.seed import seed  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.domain.enums import (  # noqa: E402
    Category,
    KnowledgeIndexStatus,
    KnowledgeSourceType,
)
from app.domain.schemas import GroundedAnswerDecision  # noqa: E402
from app.knowledge.service import KnowledgeService  # noqa: E402
from app.main import app  # noqa: E402
from app.services.agents import (  # noqa: E402
    ClassificationAgent,
    DerivationAgent,
    InitialAttentionAgent,
    PrioritizationAgent,
)
from app.services.orchestrator import OrchestratorService  # noqa: E402
from app.services.pii import PIIMaskingService  # noqa: E402

engine = create_async_engine(
    "sqlite+aiosqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def override_db() -> AsyncIterator[AsyncSession]:
    async with TestSession() as session:
        yield session


app.dependency_overrides[get_db] = override_db


def fake_embedding(text: str) -> list[float]:
    vector = [0.0] * 1536
    lowered = text.lower()
    dimensions = (
        (("fraude", "movimiento no reconocido"), 2),
        (("tarjeta", "bloqueo"), 3),
        (("banca digital",), 4),
        (("credito", "crédito"), 5),
        (("horario",), 0),
    )
    index = next(
        (index for terms, index in dimensions if any(term in lowered for term in terms)),
        1,
    )
    vector[index] = 1.0
    return vector


class FakeKnowledgeProvider:
    async def classify(self, _: str):
        raise RuntimeError("Usar clasificador determinista en pruebas")

    async def embedding(self, text: str) -> list[float]:
        return fake_embedding(text)

    async def embeddings(self, texts: list[str]) -> list[list[float]]:
        return [fake_embedding(text) for text in texts]

    async def grounded_answer(self, _: str, chunks):
        return GroundedAnswerDecision(
            answer="La línea gratuita atiende de lunes a sábado de 09:00 a 18:00.",
            supported=True,
            cited_chunk_ids=[chunks[0].chunk.id],
        )


settings_for_tests = get_settings()
fake_provider = FakeKnowledgeProvider()
test_orchestrator = OrchestratorService(
    settings=settings_for_tests,
    pii=PIIMaskingService(),
    classifier=ClassificationAgent(settings_for_tests, fake_provider),
    prioritizer=PrioritizationAgent(),
    derivation=DerivationAgent(fake_provider),
    initial_attention=InitialAttentionAgent(KnowledgeService(settings_for_tests, fake_provider)),
)
app.dependency_overrides[get_orchestrator] = lambda: test_orchestrator


@pytest_asyncio.fixture(autouse=True)
async def database() -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with TestSession() as session:
        await seed(session)
        document = KnowledgeDocument(
            slug="horarios-test",
            title="Horarios de atención",
            version="test",
            source_type=KnowledgeSourceType.OFFICIAL,
            source_urls=["https://example.test/horarios"],
            verified_at=datetime(2026, 1, 1, tzinfo=UTC),
            review_after=datetime(2030, 1, 1, tzinfo=UTC),
            file_name="horarios.pdf",
            storage_key="horarios-test.pdf",
            mime_type="application/pdf",
            byte_size=100,
            page_count=1,
            content_sha256="a" * 64,
            index_status=KnowledgeIndexStatus.READY,
            indexed_at=datetime(2026, 1, 1, tzinfo=UTC),
            active=True,
        )
        session.add(document)
        await session.flush()
        session.add(
            KnowledgeChunk(
                document_id=document.id,
                ordinal=0,
                page=1,
                section="Contact Center",
                content="La línea gratuita atiende de lunes a sábado de 09:00 a 18:00.",
                token_count=18,
                categories=[Category.CONSULTA_GENERAL.value],
                content_sha256="b" * 64,
                embedding_model="text-embedding-3-small",
                embedding=fake_embedding("horario"),
            )
        )
        await session.commit()
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.fixture
def settings():
    return get_settings()
