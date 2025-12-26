from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Generic, Optional, TypeVar


K = TypeVar("K")
V = TypeVar("V")


@dataclass
class CacheStats:
    hit_total: int = 0
    miss_total: int = 0


@dataclass
class _Entry(Generic[V]):
    value: V
    expires_at: float


class CredentialCache(Generic[K, V]):
    """
    In-memory LRU+TTL cache for secrets (process memory only).
    """

    def __init__(self, *, max_size: int = 5000) -> None:
        self._max_size = max(1, int(max_size))
        self._data: "OrderedDict[K, _Entry[V]]" = OrderedDict()
        self.stats = CacheStats()

    def get(self, key: K) -> Optional[V]:
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
        ttl = max(1, int(ttl_seconds))
        self._data[key] = _Entry(value=value, expires_at=time.time() + ttl)
        self._data.move_to_end(key)
        while len(self._data) > self._max_size:
            self._data.popitem(last=False)


class SingleFlight:
    """
    Coalesce concurrent requests for the same key.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._in_flight: dict[str, asyncio.Task[Any]] = {}

    async def do(self, key: str, fn: Callable[[], Awaitable[Any]]) -> Any:
        async with self._lock:
            existing = self._in_flight.get(key)
            if existing is not None:
                return await existing
            task = asyncio.create_task(fn())
            self._in_flight[key] = task

        try:
            return await task
        finally:
            async with self._lock:
                # Do not cache failures; always remove in-flight entry.
                self._in_flight.pop(key, None)


