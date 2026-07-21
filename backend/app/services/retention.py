import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete

from app.core.config import Settings
from app.db.models import ConversationMessage
from app.db.session import SessionFactory

logger = structlog.get_logger()


async def purge_expired_conversations(settings: Settings, session_factory=SessionFactory) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=settings.conversation_retention_days)
    async with session_factory() as db:
        result = await db.execute(
            delete(ConversationMessage).where(ConversationMessage.created_at < cutoff)
        )
        await db.commit()
        return result.rowcount or 0


async def conversation_retention_loop(settings: Settings, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            deleted = await purge_expired_conversations(settings)
            if deleted:
                logger.info("conversation_retention_purged", deleted=deleted)
        except Exception:
            logger.exception("conversation_retention_failed")
        try:
            await asyncio.wait_for(
                stop.wait(),
                timeout=settings.conversation_cleanup_hours * 3600,
            )
        except TimeoutError:
            pass
