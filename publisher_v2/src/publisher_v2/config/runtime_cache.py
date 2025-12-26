from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Generic, Optional, TypeVar


K = TypeVar("K")
V = TypeVar("V")


@dataclass
class CacheStats:
    hit_total: int = 0
    miss_total: int = 0
    stale_serve_total: int = 0


@dataclass
class _Entry(Generic[V]):
    value: V
    expires_at: float


class RuntimeConfigCache(Generic[K, V]):
    """
    In-memory LRU+TTL cache that can optionally serve stale values when upstream
    is unavailable.
    """

    def __init__(self, *, max_size: int = 1000) -> None:
        self._max_size = max(1, int(max_size))
        self._data: "OrderedDict[K, _Entry[V]]" = OrderedDict()
        self.stats = CacheStats()

    def get(self, key: K) -> tuple[Optional[V], bool]:
        """
        Returns (value, is_fresh). If missing returns (None, False).
        If expired, returns (value, False) and keeps the entry for possible stale serving.
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
        ttl = max(1, int(ttl_seconds))
        expires_at = time.time() + ttl
        self._data[key] = _Entry(value=value, expires_at=expires_at)
        self._data.move_to_end(key)

        while len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def mark_stale_served(self) -> None:
        self.stats.stale_serve_total += 1


