"""Lifespan-scoped resources shared by every MCP tool call."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.services.openai_provider import OpenAIProvider

logger = structlog.get_logger()


@dataclass(slots=True)
class AppContext:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    provider: OpenAIProvider | None


@asynccontextmanager
async def app_lifespan(_server: object) -> AsyncIterator[AppContext]:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    provider = OpenAIProvider(settings) if settings.openai_enabled else None
    logger.info("mcp_server_started", openai_enabled=settings.openai_enabled)
    try:
        yield AppContext(settings=settings, session_factory=session_factory, provider=provider)
    finally:
        await engine.dispose()
        logger.info("mcp_server_stopped")
