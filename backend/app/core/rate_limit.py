import time
from collections import defaultdict, deque
from collections.abc import Callable


class InMemoryRateLimiter:
    """Ventana móvil local con limpieza acotada de clientes inactivos."""

    def __init__(
        self,
        *,
        window_seconds: float = 60,
        prune_every: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.window_seconds = window_seconds
        self.prune_every = prune_every
        self.clock = clock
        self.windows: dict[str, deque[float]] = defaultdict(deque)
        self._checks = 0

    def allow(self, key: str, limit: int) -> bool:
        now = self.clock()
        self._checks += 1
        if self._checks % self.prune_every == 0:
            self._prune(now)

        window = self.windows[key]
        self._expire(window, now)
        if len(window) >= limit:
            return False
        window.append(now)
        return True

    def clear(self) -> None:
        self.windows.clear()
        self._checks = 0

    def _expire(self, window: deque[float], now: float) -> None:
        while window and now - window[0] > self.window_seconds:
            window.popleft()

    def _prune(self, now: float) -> None:
        stale = []
        for key, window in self.windows.items():
            self._expire(window, now)
            if not window:
                stale.append(key)
        for key in stale:
            self.windows.pop(key, None)
