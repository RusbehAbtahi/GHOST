"""Request rate limiting for the MCP prompt-engineering boundary."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Callable


@dataclass(frozen=True)
class RateLimitDecision:
    """Outcome of one rate-limit check."""

    allowed: bool
    retry_after_seconds: float = 0.0
    limit: int = 0
    window_seconds: float = 0.0


class InMemoryRateLimiter:
    """Thread-safe fixed-window limiter for one Python process."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if limit < 1:
            raise ValueError("rate-limit quota must be at least 1")
        if window_seconds <= 0:
            raise ValueError("rate-limit window must be positive")
        self._limit = int(limit)
        self._window_seconds = float(window_seconds)
        self._clock = clock
        self._lock = Lock()
        self._windows: dict[str, tuple[float, int]] = {}

    def check(self, key: str) -> RateLimitDecision:
        """Consume one quota unit for key if available."""
        caller_key = (key or "anonymous").strip() or "anonymous"
        now = float(self._clock())

        with self._lock:
            window_start, count = self._windows.get(caller_key, (now, 0))
            elapsed = now - window_start
            if elapsed >= self._window_seconds:
                window_start = now
                count = 0

            if count >= self._limit:
                retry_after = max(0.0, self._window_seconds - elapsed)
                return RateLimitDecision(False, retry_after, self._limit, self._window_seconds)

            self._windows[caller_key] = (window_start, count + 1)
            return RateLimitDecision(True, 0.0, self._limit, self._window_seconds)
