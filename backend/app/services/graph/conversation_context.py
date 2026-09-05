"""What the kiosk already knows about this conversation, shaped for one turn.

The backend answered every turn as if it were the first thing anyone had said. "¿Y los
sábados?" reached the classifier as those three words and nothing else, was embedded as
those three words, and retrieved whatever the corpus had that looked like them. The person
heard a kiosk with no memory -- and blamed the voice model, which in fact keeps the whole
exchange in its own conversation for the life of the WebRTC connection. The amnesia was
here.

The dialogue itself was already being stored: `POST /kiosk/sessions/{id}/conversation/
messages` writes every caption through `PIIMaskingService`, and until now only the caption
restore, the staff ticket view and the retention purge ever read it back. Nothing new is
persisted; this reads what is there.

Two rules the shape enforces:

- **Bounded.** Two exchanges and one active topic, capped by characters. Replaying a whole
  session into a classifier costs latency on every turn and buries the sentence that
  actually needs classifying.
- **Resolved is context, not backlog.** A question the kiosk already answered belongs here
  so a follow-up can refer to it. It must never come back as an active need -- that is how
  a credit ticket ends up carrying "también preguntó por los horarios".
"""

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CaseRecord, ConversationMessage, Requirement
from app.domain.enums import ConversationRole, ResolutionType

# How much of the exchange travels with a turn. Four messages is two full exchanges, which
# is what a reference like "¿y los sábados?" or "¿y para independientes?" reaches back to.
MAX_CONTEXT_MESSAGES = 4
# Per-message ceiling. A grounded answer can run to 1600 characters and the model does not
# need all of it to resolve a reference to it.
MAX_CONTEXT_CHARS = 320


def _clip(text: str) -> str:
    compacted = " ".join(text.split())
    if len(compacted) <= MAX_CONTEXT_CHARS:
        return compacted
    return f"{compacted[:MAX_CONTEXT_CHARS].rstrip()}…"


async def recent_exchanges(
    db: AsyncSession, session_id: UUID, *, limit: int = MAX_CONTEXT_MESSAGES
) -> list[dict[str, str]]:
    """The last few masked turns, oldest first. Already masked at write time."""
    rows = list(
        (
            await db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.session_id == session_id)
                .order_by(ConversationMessage.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    rows.reverse()
    return [
        {
            "role": "persona" if row.role is ConversationRole.CUSTOMER else "kiosco",
            "text": _clip(row.masked_text),
        }
        for row in rows
        if row.masked_text.strip()
    ]


async def resolved_topics(db: AsyncSession, session_id: UUID) -> list[str]:
    """Questions this session already settled by itself.

    Present so a follow-up can refer to them, and deliberately not fed to `additional_needs`:
    an answered question is not a pending errand, and treating it as one is what would put a
    resolved FAQ onto a credit ticket.
    """
    rows = await db.execute(
        select(Requirement.customer_summary, CaseRecord.resolution_type)
        .join(CaseRecord, CaseRecord.requirement_id == Requirement.id)
        .where(
            Requirement.session_id == session_id,
            CaseRecord.resolution_type == ResolutionType.AUTOMATIC,
        )
        .order_by(Requirement.created_at)
    )
    return [summary for summary, _ in rows if summary]


async def build_dialogue(
    db: AsyncSession,
    session_id: UUID,
    *,
    latest_customer_reply: str,
    active_topic: str | None,
    active_category: str | None,
    clarification: dict | None = None,
) -> dict:
    """The `dialogue` envelope the classification prompt already knows how to read."""
    dialogue: dict = {
        "latest_customer_reply": latest_customer_reply,
        "recent_exchanges": await recent_exchanges(db, session_id),
    }
    if active_topic:
        dialogue["active_topic"] = active_topic
    if active_category:
        dialogue["active_category"] = active_category
    settled = await resolved_topics(db, session_id)
    if settled:
        dialogue["resolved_topics"] = settled
    if clarification:
        dialogue.update(clarification)
    return dialogue


def as_classification_input(dialogue: dict) -> str:
    return json.dumps({"dialogue": dialogue}, ensure_ascii=False)
