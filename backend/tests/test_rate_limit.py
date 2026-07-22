from app.core.rate_limit import InMemoryRateLimiter


def test_rate_limiter_preserves_window_and_prunes_stale_clients() -> None:
    now = [0.0]
    limiter = InMemoryRateLimiter(prune_every=1, clock=lambda: now[0])

    assert limiter.allow("client-a", 2)
    assert limiter.allow("client-a", 2)
    assert not limiter.allow("client-a", 2)
    assert limiter.allow("client-b", 1)

    now[0] = 61.0
    assert limiter.allow("client-c", 1)
    assert "client-a" not in limiter.windows
    assert "client-b" not in limiter.windows
    assert limiter.allow("client-a", 2)
