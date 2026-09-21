"""In-memory LRU + TTL cache backing the orchestrator runtime-config lookups.

Holds decoded runtime configuration per host so that a per-request lookup does
not become a per-request call to the orchestrator, and keeps expired entries
around so callers can deliberately serve stale config when the orchestrator is
unreachable.
"""

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass(slots=True)
class CacheStats:
    """Counters for one cache instance, exposed for metrics/observability.

    ``miss_total`` counts both absent keys and expired-but-present entries;
    ``stale_serve_total`` is bumped by the caller via ``mark_stale_served``
    only when it actually decided to use an expired value.
    """

    hit_total: int = 0
    miss_total: int = 0
    stale_serve_total: int = 0


@dataclass(frozen=True, slots=True)
class _Entry[V]:
    """One cached value together with its absolute expiry timestamp (epoch seconds)."""

    value: V
    expires_at: float


class RuntimeConfigCache[K, V]:
    """Cache runtime values with an LRU bound and per-entry TTL.

    In-memory LRU+TTL cache that can optionally serve stale values when upstream
    is unavailable: expired entries are kept (and still returned, flagged as not
    fresh) until evicted by the size bound, so a caller can fall back to them.
    Not thread-safe and not shared between processes; each worker has its own.
    """

    def __init__(self, *, max_size: int = 1000) -> None:
        """Create an empty cache bounded to ``max_size`` entries (coerced to at least 1).

        Eviction is least-recently-used, counting both reads and writes as use.
        """
        self._max_size = max(1, int(max_size))
        self._data: OrderedDict[K, _Entry[V]] = OrderedDict()
        self.stats = CacheStats()

    def get(self, key: K) -> tuple[V | None, bool]:
        """Look up ``key`` and report whether the value is still fresh.

        Returns (value, is_fresh). If missing returns (None, False).
        If expired, returns (value, False) and keeps the entry for possible stale serving.
        A hit — fresh or not — also refreshes the entry's LRU position.
        """
        entry = self._data.get(key)
        if entry is None:
            self.stats.miss_total += 1
            return None, False

        # LRU touch
        self._data.move_to_end(key)
        now = time.time()
        if now <= entry.expires_at:
            self.stats.hit_total += 1
            return entry.value, True

        # Expired but present
        self.stats.miss_total += 1
        return entry.value, False

    def set(self, key: K, value: V, *, ttl_seconds: int) -> None:
        """Store ``value`` under ``key`` for ``ttl_seconds`` (coerced to at least 1 second).

        Replaces any existing entry, marks it most-recently-used, and evicts the
        least-recently-used entries until the size bound holds again.
        """
        ttl = max(1, int(ttl_seconds))
        expires_at = time.time() + ttl
        self._data[key] = _Entry(value=value, expires_at=expires_at)
        self._data.move_to_end(key)

        while len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def mark_stale_served(self) -> None:
        """Record that the caller served an expired value because upstream was unavailable.

        The cache cannot detect this itself — ``get`` only reports staleness —
        so the fallback path must call this for the counter to be meaningful.
        """
        self.stats.stale_serve_total += 1
