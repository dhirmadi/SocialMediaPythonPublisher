"""Sliding-window in-memory rate limiter for FastAPI routes.

This is a process-local limiter — fine for a single-worker deployment. Larger
deployments should swap the backing store for Redis or similar.

Usage::

    ANALYZE_LIMITER = SlidingWindowLimiter(window_seconds=60, max_events=10)

    def analyze_route(request: Request):
        ANALYZE_LIMITER.check(request_key(request))
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
                if len(self._events) >= self._max_keys:
                    # #91 (SEC-10): refuse new keys rather than growing without
                    # bound when GC frees nothing (key-flood protection).
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Rate limiter at key capacity ({self._label})",
                        headers={"Retry-After": str(int(self._window))},
                    )
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
    """Best-effort client IP. Falls back to "unknown" rather than mixing buckets.

    Honours X-Forwarded-For only when WEB_TRUST_FORWARDED_FOR is set, and takes
    the RIGHTMOST entry: Heroku's router appends the real client IP to the end
    of the header, so every entry to its left is attacker-supplied. Taking the
    leftmost entry would let a client mint a fresh rate-limit key per request.
    """
    if trust_forwarded_headers():
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.rsplit(",", 1)[-1].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def trust_forwarded_headers() -> bool:
    """True when WEB_TRUST_FORWARDED_FOR says the app sits behind a trusted proxy (Heroku router)."""
    import os

    return os.environ.get("WEB_TRUST_FORWARDED_FOR", "").lower() in ("1", "true", "yes")


def forwarded_proto_values(request: Request) -> list[str]:
    """Every ``X-Forwarded-Proto`` value, normalised, across duplicate header lines.

    Starlette keeps duplicate header lines separately (``getlist``) while
    ``get`` returns only the first, so the comma form and the repeated-header
    form are the same input in two spellings and both have to be read.
    """
    return [
        value.strip().lower()
        for line in request.headers.getlist("x-forwarded-proto")
        for value in line.split(",")
        if value.strip()
    ]


def request_scheme(request: Request) -> str:
    """Client-facing scheme of ``request``.

    Heroku's router is not loopback, so uvicorn's own proxy-header handling
    (``FORWARDED_ALLOW_IPS``, default 127.0.0.1) never rewrites
    ``request.url.scheme`` there (#129). When WEB_TRUST_FORWARDED_FOR is set we
    read ``X-Forwarded-Proto`` ourselves.

    A header carrying values that DISAGREE is not trusted, and the scheme falls
    back to the connection's own. The leftmost value is not usable on its own:
    if a client sends ``X-Forwarded-Proto: https`` and a proxy appends its own
    ``http``, the leftmost entry is the client's forgery. Values that all agree
    are accepted, whether they arrived as one value, as ``https, https`` or as
    repeated header lines — that is the shape a chain of TLS-terminating
    proxies produces (Cloudflare in Full mode in front of Heroku), and refusing
    it would bring the 403 back in a deployment we actively recommend.

    Deliberately not symmetric with ``remote_ip``, which takes the RIGHTMOST
    X-Forwarded-For entry. X-Forwarded-For is appended to by contract, so its
    rightmost entry is the one the trusted proxy wrote. X-Forwarded-Proto
    describes the client-facing hop rather than a chain of hops, so no position
    in a disagreeing list is trustworthy and agreement is the only usable
    signal. uvicorn's ProxyHeadersMiddleware is stricter still and drops any
    multi-valued header outright.
    """
    if trust_forwarded_headers():
        values = forwarded_proto_values(request)
        if values and all(value == values[0] for value in values) and values[0] in ("http", "https"):
            return values[0]
    return request.url.scheme
