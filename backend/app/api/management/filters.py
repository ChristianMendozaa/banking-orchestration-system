"""Period defaults, the shared filter set, and the percentile helper.

`LA_PAZ` is what makes "today" mean the branch's today rather than UTC's: the
default reporting period is midnight-to-midnight in Bolivia, converted to UTC only
at the boundary.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import (
    CaseRecord,
    Ticket,
)
from app.domain.enums import Category, Priority

LA_PAZ = ZoneInfo("America/La_Paz")


def default_period() -> tuple[datetime, datetime]:
    now = datetime.now(LA_PAZ)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def build_filters(
    date_from: datetime | None,
    date_to: datetime | None,
    category: Category | None,
    priority: Priority | None,
    executive_id: UUID | None,
):
    default_from, default_to = default_period()
    if date_from and not date_from.tzinfo:
        date_from = date_from.replace(tzinfo=LA_PAZ)
    if date_to and not date_to.tzinfo:
        date_to = date_to.replace(tzinfo=LA_PAZ)
    start = date_from.astimezone(UTC) if date_from else default_from
    end = date_to.astimezone(UTC) if date_to else default_to
    result = [Ticket.created_at >= start, Ticket.created_at < end]
    if category:
        result.append(CaseRecord.category == category)
    if priority:
        result.append(CaseRecord.priority == priority)
    if executive_id:
        result.append(Ticket.executive_id == executive_id)
    return result, start, end


def query_with_relations():
    return select(Ticket).options(selectinload(Ticket.case), selectinload(Ticket.executive))


def percentile_of(values: list[float], percentile: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)
