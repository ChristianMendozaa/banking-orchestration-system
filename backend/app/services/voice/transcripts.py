"""Persist conversation turns, masked, exactly once.

Both transports write here: the HTTP `/conversation/messages` sync used by text mode, and
the voice session. Voice used to write through the browser, which is why this had to be
idempotent on an externally supplied item id -- it still does, because a reconnecting
client replays what it has.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConversationMessage, KioskSession
from app.services.pii import PIIMaskingService


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    item_id: str
    role: str
    text: str


async def record_messages(
    db: AsyncSession,
    kiosk_session: KioskSession,
    messages: list[IncomingMessage],
    pii: PIIMaskingService | None = None,
) -> int:
    """Store any of `messages` not already stored. Returns how many were new."""
    if not messages:
        return 0
    masker = pii or PIIMaskingService()
    item_ids = [message.item_id for message in messages]
    existing = set(
        (
            await db.scalars(
                select(ConversationMessage.external_item_id).where(
                    ConversationMessage.session_id == kiosk_session.id,
                    ConversationMessage.external_item_id.in_(item_ids),
                )
            )
        ).all()
    )
    created = 0
    for message in messages:
        if message.item_id in existing:
            continue
        db.add(
            ConversationMessage(
                session_id=kiosk_session.id,
                external_item_id=message.item_id,
                role=message.role,
                masked_text=masker.mask(message.text).masked_text,
            )
        )
        existing.add(message.item_id)
        created += 1
    return created
