"""Reset the kiosk's operational queue before a live eval run.

`make evals-live` runs the whole scenario catalog against a real backend and never resets
anything, so tickets accumulate across runs: `estimated_wait_minutes` is `(active_load + 1) *
estimated_service_minutes`, and `active_load` counts every `PENDIENTE`/`EN_ATENCION` ticket
ever created (`app/db/repositories.py::ExecutiveRepository.active_loads`). After a handful of
runs the reported waits are in the hundreds of minutes and say nothing about how the session
under test was actually handled -- judge notes in `backend/evals/reports/runs/` cite a
"344-minute wait" against otherwise-correct handoffs.

Deleting every `KioskSession` row is sufficient: `Requirement`, `CaseRecord`,
`ConversationMessage`, and (through `CaseRecord`) `Identification`, `Ticket` and `TraceEvent`
all cascade on delete at the database level (see the `ForeignKey(..., ondelete="CASCADE")`
declarations in `app/db/models.py`). `Executive` rows and the knowledge base are never
touched -- re-embedding the corpus on every reset would turn a free cleanup into a billed
one.

Usage: `uv run python scripts/reset_kiosk_queue.py` (from `backend/`), or via
`make evals-live`, which calls it automatically before the harness runs.
"""

import asyncio

from sqlalchemy import delete, func, select

from app.db.models import KioskSession
from app.db.session import SessionFactory


async def main() -> None:
    async with SessionFactory() as db:
        (before,) = (await db.execute(select(func.count()).select_from(KioskSession))).one()
        await db.execute(delete(KioskSession))
        await db.commit()
    print(f"Cola del kiosco reiniciada: {before} sesion(es) y su historial en cascada eliminados.")


if __name__ == "__main__":
    asyncio.run(main())
