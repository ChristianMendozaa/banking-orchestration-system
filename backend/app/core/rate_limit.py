import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass

from redis.asyncio import Redis


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int = 0


class InMemoryRateLimiter:
    """Local sliding window with bounded cleanup of idle clients."""

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

    def check(self, key: str, limit: int) -> RateLimitDecision:
        allowed = self.allow(key, limit)
        if allowed:
            return RateLimitDecision(True)
        window = self.windows[key]
        retry_after = max(1, int(self.window_seconds - (self.clock() - window[0])) + 1)
        return RateLimitDecision(False, retry_after)

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


class RedisRateLimiter:
    """Shared, atomic fixed window for deployments with more than one process."""

    _SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""

    def __init__(self, url: str, *, window_seconds: int = 60) -> None:
        self.redis = Redis.from_url(url, encoding="utf-8", decode_responses=True)
        self.window_seconds = window_seconds

    async def check(self, key: str, limit: int) -> RateLimitDecision:
        current, ttl = await self.redis.eval(
            self._SCRIPT,
            1,
            f"orquestacion:rate:{key}",
            self.window_seconds,
        )
        allowed = int(current) <= limit
        return RateLimitDecision(allowed, 0 if allowed else max(1, int(ttl)))

    async def close(self) -> None:
        await self.redis.aclose()
