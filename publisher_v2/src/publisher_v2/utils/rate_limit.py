from __future__ import annotations

import asyncio
import time


class AsyncRateLimiter:
    """
    Minimal async rate limiter to space calls across time.
    Ensures a minimum interval between successive acquires.
    """

    def __init__(self, rate_per_minute: int = 20) -> None:
        self._min_interval = 60.0 / max(rate_per_minute, 1)
        self._lock = asyncio.Lock()
        self._last_time = 0.0

    async def __aenter__(self) -> "AsyncRateLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_time = time.monotonic()


