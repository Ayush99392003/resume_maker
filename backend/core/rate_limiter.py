"""Per-user in-process sliding-window rate limiter for /chat."""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Dict

from core.logging_setup import get_logger

log = get_logger("rate_limiter")

# Maximum chat requests per user (or IP) per 60-second rolling window.
# Override via MAX_CHAT_PER_MINUTE env var.
_MAX_PER_MIN: int = int(os.getenv("MAX_CHAT_PER_MINUTE", "10"))
_WINDOW_SECS: float = 60.0


class RateLimiter:
    """Thread-safe sliding-window rate limiter keyed by an arbitrary string.

    Uses a ``collections.deque`` of timestamps per key so memory is bounded
    to ``max_calls`` timestamps per active user.
    """

    def __init__(
        self,
        max_calls: int = _MAX_PER_MIN,
        window_secs: float = _WINDOW_SECS,
    ) -> None:
        self._max_calls = max_calls
        self._window = window_secs
        self._buckets: Dict[str, deque] = {}
        self._lock = threading.Lock()

    def check_and_record(self, key: str) -> bool:
        """Return True if the request is allowed; False if the limit is hit.

        Records the current timestamp on success so subsequent calls count it.
        """
        now = time.monotonic()
        cutoff = now - self._window

        with self._lock:
            if key not in self._buckets:
                self._buckets[key] = deque()

            bucket = self._buckets[key]

            # Evict timestamps outside the rolling window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= self._max_calls:
                log.warning(
                    "rate_limiter: limit hit key=%s calls_in_window=%s "
                    "max=%s window_secs=%s",
                    key,
                    len(bucket),
                    self._max_calls,
                    self._window,
                )
                return False

            bucket.append(now)
            return True

    def remaining(self, key: str) -> int:
        """Return how many calls remain in the current window (informational)."""
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            bucket = self._buckets.get(key, deque())
            in_window = sum(1 for t in bucket if t >= cutoff)
            return max(0, self._max_calls - in_window)

    def reset(self, key: str) -> None:
        """Clear the bucket for *key* (useful in tests)."""
        with self._lock:
            self._buckets.pop(key, None)


# Module-level singleton shared across all requests in the process.
chat_rate_limiter = RateLimiter()
