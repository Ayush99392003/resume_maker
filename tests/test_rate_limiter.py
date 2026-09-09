"""Unit tests for the in-process sliding-window rate limiter."""

from __future__ import annotations

import sys
import time
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from core.rate_limiter import RateLimiter


def test_rate_limiter_allow_under_limit():
    """Requests under max_calls are allowed."""
    limiter = RateLimiter(max_calls=3, window_secs=10.0)
    user = "test_user_allow"
    assert limiter.check_and_record(user) is True
    assert limiter.check_and_record(user) is True
    assert limiter.check_and_record(user) is True


def test_rate_limiter_blocks_over_limit():
    """Fourth request exceeding max_calls=3 is blocked."""
    limiter = RateLimiter(max_calls=3, window_secs=10.0)
    user = "test_user_block"
    for _ in range(3):
        assert limiter.check_and_record(user) is True
    assert limiter.check_and_record(user) is False
    assert limiter.remaining(user) == 0


def test_rate_limiter_user_isolation():
    """Exhausting limit for user A does not affect user B."""
    limiter = RateLimiter(max_calls=2, window_secs=10.0)
    user_a = "user_alpha"
    user_b = "user_beta"

    assert limiter.check_and_record(user_a) is True
    assert limiter.check_and_record(user_a) is True
    assert limiter.check_and_record(user_a) is False

    # User B should still have full quota
    assert limiter.remaining(user_b) == 2
    assert limiter.check_and_record(user_b) is True
    assert limiter.check_and_record(user_b) is True
    assert limiter.check_and_record(user_b) is False


def test_rate_limiter_window_expiry():
    """After window duration passes, calls are allowed again."""
    short_window = 0.2
    limiter = RateLimiter(max_calls=2, window_secs=short_window)
    user = "test_user_expiry"

    assert limiter.check_and_record(user) is True
    assert limiter.check_and_record(user) is True
    assert limiter.check_and_record(user) is False

    time.sleep(short_window + 0.05)

    assert limiter.check_and_record(user) is True
    assert limiter.remaining(user) == 1
