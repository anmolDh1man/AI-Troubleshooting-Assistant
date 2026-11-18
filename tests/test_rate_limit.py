"""Per-session sliding-window rate limit (Phase 4). Time is injected, so the tests are instant."""

from src.rate_limit import SessionRateLimiter


def test_requests_within_the_limit_are_allowed_then_blocked():
    limiter = SessionRateLimiter(max_requests=3, window_seconds=60)
    assert [limiter.allow(now=t) for t in (0, 1, 2)] == [True, True, True]
    assert limiter.allow(now=3) is False
    assert limiter.used == 3  # a blocked request is not recorded


def test_window_slides():
    limiter = SessionRateLimiter(max_requests=2, window_seconds=10)
    assert limiter.allow(now=0) and limiter.allow(now=5)
    assert not limiter.allow(now=9)
    assert limiter.allow(now=10)       # the request at t=0 has left the window
    assert not limiter.allow(now=11)
    assert limiter.allow(now=15)       # the request at t=5 has left the window


def test_retry_after_counts_down():
    limiter = SessionRateLimiter(max_requests=1, window_seconds=30)
    assert limiter.retry_after(now=0) == 0
    limiter.allow(now=0)
    assert limiter.retry_after(now=0) == 30
    assert limiter.retry_after(now=20.5) == 10
    assert limiter.retry_after(now=30) == 0
