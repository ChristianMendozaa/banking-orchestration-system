"""Report where the classified transcript diverges from what the customer actually said.

The kiosk records two independent versions of every spoken turn. `conversation_messages`
holds the voice session's own audio transcription, synced from the browser. `requirements`
holds the text that was actually masked, classified, prioritised and routed. They are
supposed to be the same sentence.

On 2026-08-19 they were not: a customer said "Quiero reportar el robo de mi tarjeta de
debito", the transcription recorded exactly that, and the requirement was classified from
"Quiero portar el juego de mi tarjeta de debito" -- because the realtime model retyped the
sentence into its tool call instead of the application passing the transcription through.
The orchestrator then behaved correctly on a sentence nobody had said.

That is now fixed at the source (`frontend/components/providers/kiosk-provider.tsx` resolves
the transcript from the session's captions), and this script is the standing check that it
stays fixed. It reads live sessions -- no audio harness, no synthetic scenarios -- so it
works against real branch traffic as well as a local run.

Usage: `uv run python scripts/check_transcript_fidelity.py [--since-hours 24]`
Exits non-zero when any turn diverges.
"""

import argparse
import asyncio
import re
import unicodedata
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import ConversationMessage, KioskSession, Requirement
from app.db.session import SessionFactory

# Below this share of shared word-pairs, the two versions are not the same sentence. Word
# pairs rather than words: the corruption that motivated this replaced the two words carrying
# the meaning and left the rest intact, which single-word overlap scores as 0.6 similar.
SIMILARITY_FLOOR = 0.6
_CLARIFICATION_JOINER = "\nAclaracion: "


def _normalise(value: str) -> list[str]:
    folded = unicodedata.normalize("NFD", value.casefold())
    stripped = "".join(char for char in folded if not unicodedata.combining(char))
    return [word for word in re.sub(r"[^\w\s]", " ", stripped).split() if word]


def _shingles(value: str) -> set[str]:
    words = _normalise(value)
    if len(words) < 2:
        return set(words)
    return {f"{word} {words[index + 1]}" for index, word in enumerate(words[:-1])}


def similarity(left: str, right: str) -> float:
    first, second = _shingles(left), _shingles(right)
    if not first or not second:
        return 1.0
    shared = len(first & second)
    return shared / len(first | second)


async def main(since_hours: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(hours=since_hours)
    divergences = 0
    checked = 0
    async with SessionFactory() as db:
        session_ids = (
            await db.scalars(select(KioskSession.id).where(KioskSession.created_at >= cutoff))
        ).all()
        for session_id in session_ids:
            spoken = list(
                (
                    await db.scalars(
                        select(ConversationMessage)
                        .where(
                            ConversationMessage.session_id == session_id,
                            ConversationMessage.role == "CUSTOMER",
                        )
                        .order_by(ConversationMessage.created_at)
                    )
                ).all()
            )
            if not spoken:
                # A text-only session: the customer typed, so there is nothing to compare.
                continue
            requirements = list(
                (
                    await db.scalars(
                        select(Requirement)
                        .where(Requirement.session_id == session_id)
                        .order_by(Requirement.created_at)
                    )
                ).all()
            )
            utterances = [message.masked_text.strip() for message in spoken]
            for index, requirement in enumerate(requirements):
                # A clarification requirement carries the whole running context; only the
                # part after the joiner corresponds to this turn's utterance.
                classified = requirement.masked_text.rsplit(_CLARIFICATION_JOINER, 1)[-1].strip()
                if not classified:
                    continue
                # Best match rather than position: not every spoken turn becomes a
                # requirement (a bare "si" answers a confirmation), so positional alignment
                # drifts and would report divergences that are really just an offset. A
                # requirement that closely matches *some* thing the customer said was
                # classified from words they actually used, whichever turn it was.
                said, score = max(
                    ((utterance, similarity(utterance, classified)) for utterance in utterances),
                    key=lambda pair: pair[1],
                    default=("", 1.0),
                )
                checked += 1
                if score >= SIMILARITY_FLOOR:
                    continue
                divergences += 1
                print(f"\nsesion {session_id} turno {index + 1}  (similitud {score:.2f})")
                print(f"  dijo        : {said}")
                print(f"  se clasifico: {classified}")

    print(f"\n{checked} turno(s) de voz revisado(s); {divergences} divergencia(s).")
    return 1 if divergences else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since-hours", type=int, default=24)
    raise SystemExit(asyncio.run(main(parser.parse_args().since_hours)))
