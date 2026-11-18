"""Per-session sliding-window rate limit (RATE_LIMIT_REQUESTS per RATE_LIMIT_WINDOW_SECONDS).

Scope: one browser session (st.session_state). It stops a single tab from flooding the app, but it is
NOT a global or per-IP limit: a new session (reload, new tab, script) starts with a fresh window.
Global and per-IP limits need infrastructure in front of Streamlit (reverse proxy, API gateway or WAF);
see OPERATIONS.md.
"""

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class SessionRateLimiter:
    max_requests: int
    window_seconds: float
    _timestamps: deque = field(default_factory=deque)

    def _prune(self, now: float) -> None:
        while self._timestamps and now - self._timestamps[0] >= self.window_seconds:
            self._timestamps.popleft()

    def allow(self, now: float | None = None) -> bool:
        """Record and allow a request, or return False (nothing recorded) when the window is full."""
        now = time.monotonic() if now is None else now
        self._prune(now)
        if len(self._timestamps) >= self.max_requests:
            return False
        self._timestamps.append(now)
        return True

    def retry_after(self, now: float | None = None) -> int:
        """Whole seconds until the next request would be allowed (0 if allowed now)."""
        now = time.monotonic() if now is None else now
        self._prune(now)
        if len(self._timestamps) < self.max_requests:
            return 0
        return max(1, int(self.window_seconds - (now - self._timestamps[0]) + 0.999))

    @property
    def used(self) -> int:
        return len(self._timestamps)
