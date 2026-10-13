"""In-process rate limiting and concurrency gating for /analyze.

Every analysis request spends real money at a third-party detector (BitMind for
images/videos, Reality Defender for audio), so the public endpoint must not be
freely loopable by anyone who loads the URL.

Deliberately in-memory: this protects the single-process deployment that
`server.js` runs, without adding a Redis dependency. If this service is ever
run with multiple workers or instances, move the counters to a shared store —
each process would otherwise enforce its own independent budget.
"""

import os
import threading
import time
from collections import deque

from fastapi import Request


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


# Requests allowed per client per window, and how many analyses may run at once.
WINDOW_SECONDS = float(_env_int("RATE_LIMIT_WINDOW_SECONDS", 600))
MAX_REQUESTS = _env_int("RATE_LIMIT_MAX_REQUESTS", 30)
MAX_CONCURRENT = _env_int("RATE_LIMIT_MAX_CONCURRENT", 3)

# Cap the number of tracked clients so a flood of spoofed identities cannot
# grow the dict without bound.
_MAX_TRACKED_CLIENTS = 10_000


def client_identity(request: Request) -> str:
    """Best-effort client identity for rate limiting.

    `server.js` proxies same-origin requests, so `request.client.host` is
    always loopback in that setup — trusting it alone would put every visitor
    in one shared bucket. Use the forwarded chain when present and fall back to
    the socket address.
    """

    forwarded = request.headers.get("x-forwarded-for", "")

    if forwarded:
        first = forwarded.split(",")[0].strip()

        if first:
            return first

    real_ip = request.headers.get("x-real-ip", "").strip()

    if real_ip:
        return real_ip

    if request.client and request.client.host:
        return request.client.host

    return "unknown"


class SlidingWindowLimiter:
    """Allow at most `max_requests` per `window_seconds`, per key."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._lock = threading.Lock()
        self._hits: dict[str, deque] = {}

    def check(self, key: str) -> float:
        """Record one attempt. Returns 0.0 if allowed, else seconds to wait."""

        now = time.monotonic()
        cutoff = now - self._window_seconds

        with self._lock:
            if len(self._hits) > _MAX_TRACKED_CLIENTS:
                self._hits.clear()

            bucket = self._hits.setdefault(key, deque())

            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= self._max_requests:
                return self._window_seconds - (now - bucket[0])

            bucket.append(now)

        return 0.0


class ConcurrencyGate:
    """Bound how many expensive analyses run simultaneously."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._active = 0
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        with self._lock:
            if self._active >= self._limit:
                return False

            self._active += 1

        return True

    def release(self) -> None:
        with self._lock:
            if self._active > 0:
                self._active -= 1


request_limiter = SlidingWindowLimiter(MAX_REQUESTS, WINDOW_SECONDS)
analysis_slots = ConcurrencyGate(MAX_CONCURRENT)
