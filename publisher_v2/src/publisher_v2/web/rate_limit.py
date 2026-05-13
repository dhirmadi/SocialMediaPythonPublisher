"""Sliding-window in-memory rate limiter for FastAPI routes.

This is a process-local limiter — fine for a single-worker deployment. Larger
deployments should swap the backing store for Redis or similar.

Usage::

    LOGIN_LIMITER = SlidingWindowLimiter(window_seconds=900, max_events=5)

    def login_route(request: Request):
        LOGIN_LIMITER.check(request_key(request))
        ...

``request_key`` should be ``remote_ip(request)`` for anonymous endpoints and
``f"admin:{admin_id}"`` for authenticated endpoints so one noisy admin cannot
DoS another.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class SlidingWindowLimiter:
    def __init__(self, *, window_seconds: float, max_events: int, label: str = "rate_limited") -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        if max_events <= 0:
            raise ValueError("max_events must be > 0")
        self._window = float(window_seconds)
        self._max = int(max_events)
        self._label = label
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        # Cap the number of keys to bound memory under attack.
        self._max_keys = 10_000

    def check(self, key: str) -> None:
        """Record an event for ``key``. Raises HTTPException(429) when exceeded."""
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            if len(self._events) >= self._max_keys and key not in self._events:
                self._gc_locked(cutoff)
            bucket = self._events[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._max:
                retry_after = max(1, int(self._window - (now - bucket[0])))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded ({self._label}); retry in {retry_after}s",
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)

    def reset(self, key: str | None = None) -> None:
        """Clear state for a single key, or all keys when ``key`` is None."""
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)

    def _gc_locked(self, cutoff: float) -> None:
        """Drop empty buckets and prune stale entries (caller holds the lock)."""
        stale = [k for k, q in self._events.items() if not q or q[-1] < cutoff]
        for k in stale:
            self._events.pop(k, None)


def remote_ip(request: Request) -> str:
    """Best-effort client IP. Falls back to "unknown" rather than mixing buckets."""
    # Honour X-Forwarded-For only when a trusted-proxy env var is set —
    # otherwise an attacker can spoof the header and bypass per-IP limits.
    import os

    if os.environ.get("WEB_TRUST_FORWARDED_FOR", "").lower() in ("1", "true", "yes"):
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"
