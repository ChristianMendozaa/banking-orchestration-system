"""Executive ticket operations, split into routes, queries and serializers.

`router` and `ticket_item` stay importable from `app.api.tickets`, so `app/main.py`
and every test are unchanged.
"""

from app.api.tickets.router import router
from app.api.tickets.serializers import ticket_item

__all__ = ["router", "ticket_item"]
