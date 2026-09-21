"""Process-local async rate limiter used to pace outbound API calls."""

import asyncio
import time


class AsyncRateLimiter:
    """Minimal async rate limiter to space calls across time.

    Ensures a minimum interval between successive acquires.
    """

    def __init__(self, rate_per_minute: int = 20) -> None:
        """Set the pacing budget; values below 1 per minute are clamped to 1.

        Args:
            rate_per_minute: Maximum acquires per minute, converted to a
                minimum interval of ``60 / rate_per_minute`` seconds.
        """
        self._min_interval = 60.0 / max(rate_per_minute, 1)
        self._lock = asyncio.Lock()
        self._last_time = 0.0

    async def __aenter__(self) -> "AsyncRateLimiter":
        """Wait for the pacing slot, then yield this limiter."""
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Release nothing; the slot is consumed on entry and exceptions propagate."""
        return None

    async def acquire(self) -> None:
        """Sleep until the minimum interval since the previous acquire has elapsed.

        Serialised by an internal lock, so concurrent callers are paced one at a
        time rather than all waking together.
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_time = time.monotonic()
