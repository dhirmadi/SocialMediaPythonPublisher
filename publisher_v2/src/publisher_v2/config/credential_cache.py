"""In-memory caching primitives for resolved credential material.

Secrets resolved from the orchestrator are held here for a short TTL so that a
burst of requests does not re-resolve the same credential. Nothing in this
module persists to disk or logs cached values.
"""

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass(slots=True)
class CacheStats:
    """Counters for cache lookups, exposed for metrics and tests.

    A lookup of an expired entry counts as a miss, not a hit.
    """

    hit_total: int = 0
    miss_total: int = 0


@dataclass(frozen=True, slots=True)
class _Entry[V]:
    value: V
    expires_at: float


class CredentialCache[K, V]:
    """In-memory LRU+TTL cache for secrets (process memory only)."""

    def __init__(self, *, max_size: int = 5000) -> None:
        """Create an empty cache bounded to ``max_size`` entries (minimum 1).

        Once the bound is exceeded the least recently used entries are evicted.
        Entries are never written to disk; they live only in process memory.
        """
        self._max_size = max(1, int(max_size))
        self._data: OrderedDict[K, _Entry[V]] = OrderedDict()
        self.stats = CacheStats()

    def get(self, key: K) -> V | None:
        """Return the cached value for ``key``, or ``None`` if absent or expired.

        An expired entry is evicted as a side effect. Hits refresh the entry's
        recency, so the returned key is the last candidate for LRU eviction.
        """
        entry = self._data.get(key)
        if entry is None:
            self.stats.miss_total += 1
            return None

        self._data.move_to_end(key)
        if time.time() > entry.expires_at:
            # Expired: remove and treat as miss
            self._data.pop(key, None)
            self.stats.miss_total += 1
            return None

        self.stats.hit_total += 1
        return entry.value

    def set(self, key: K, value: V, *, ttl_seconds: int) -> None:
        """Store ``value`` under ``key``, expiring ``ttl_seconds`` from now.

        A TTL below one second is clamped to one second. Writing may evict the
        least recently used entries to stay within the configured maximum size.
        """
        ttl = max(1, int(ttl_seconds))
        self._data[key] = _Entry(value=value, expires_at=time.time() + ttl)
        self._data.move_to_end(key)
        while len(self._data) > self._max_size:
            self._data.popitem(last=False)


class SingleFlight:
    """Coalesce concurrent requests for the same key."""

    def __init__(self) -> None:
        """Create an empty in-flight registry with its own asyncio lock.

        The instance is bound to the event loop it is first awaited on and is
        not safe to share across loops or threads.
        """
        self._lock = asyncio.Lock()
        self._in_flight: dict[str, asyncio.Task[Any]] = {}

    async def do(self, key: str, fn: Callable[[], Awaitable[Any]]) -> Any:
        """Run ``fn`` for ``key``, or await the call already in flight for it.

        Every waiter observes the same result, including the same exception if
        ``fn`` raises. Failures are not cached: the in-flight entry is always
        cleared, so the next caller re-runs ``fn``.
        """
        async with self._lock:
            existing = self._in_flight.get(key)
            if existing is not None:
                return await existing
            task: asyncio.Task[Any] = asyncio.create_task(fn())  # type: ignore[arg-type]
            self._in_flight[key] = task

        try:
            return await task
        finally:
            async with self._lock:
                # Do not cache failures; always remove in-flight entry.
                self._in_flight.pop(key, None)
