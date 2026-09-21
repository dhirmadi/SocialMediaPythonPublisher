"""Fire-and-forget usage metering for orchestrated mode.

#93 (PERF-3): ``emit`` enqueues and returns immediately; a single background
drainer task posts queued events in batches so the analyze/publish request
path never waits on a metering round-trip. ``aclose()`` flushes what remains.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from publisher_v2.core.models import AIUsage
from publisher_v2.utils.logging import log_json

if TYPE_CHECKING:
    from publisher_v2.config.orchestrator_client import OrchestratorClient

_QUEUE_MAX = 1000
_BATCH_MAX = 20


class UsageMeter:
    """Emit AI token usage events to the orchestrator billing endpoint.

    All exceptions are caught and logged — metering never blocks or breaks the
    workflow. Events carry the OpenAI response id as idempotency key, so a
    duplicate post is deduped upstream.
    """

    def __init__(self, client: OrchestratorClient, tenant_id: str) -> None:
        """Bind the meter to one orchestrator client and the tenant that is billed.

        The bounded queue (``_QUEUE_MAX`` events) and the background drainer are
        created lazily on first ``emit``, so constructing a meter outside a
        running event loop is safe.
        """
        self._client = client
        self._tenant_id = tenant_id
        self._logger = logging.getLogger("publisher_v2.metering")
        self._queue: asyncio.Queue[tuple[AIUsage, str, str]] = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._drainer: asyncio.Task[None] | None = None

    async def emit(self, usage: AIUsage, metric: str = "ai_tokens", unit: str = "tokens") -> None:
        """Enqueue one usage event and return immediately. Never raises."""
        if usage is None or usage.total_tokens <= 0:
            return
        try:
            self._queue.put_nowait((usage, metric, unit))
        except asyncio.QueueFull:
            log_json(
                self._logger,
                logging.WARNING,
                "usage_metering_queue_full",
                metric=metric,
                quantity=usage.total_tokens,
                tenant_id=self._tenant_id,
            )
            return
        self._ensure_drainer()

    async def emit_all(self, usages: list[AIUsage], metric: str = "ai_tokens", unit: str = "tokens") -> None:
        """Enqueue usage for all non-None, non-zero entries."""
        for u in usages:
            if u is not None and u.total_tokens > 0:
                await self.emit(u, metric=metric, unit=unit)

    def _ensure_drainer(self) -> None:
        if self._drainer is not None and not self._drainer.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover — no loop (sync test context)
            return
        self._drainer = loop.create_task(self._drain_loop())

    async def _drain_loop(self) -> None:
        while True:
            first = await self._queue.get()
            batch = [first]
            while len(batch) < _BATCH_MAX:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            try:
                await asyncio.gather(*(self._post(u, m, un) for u, m, un in batch))
            finally:
                for _ in batch:
                    self._queue.task_done()

    async def _post(self, usage: AIUsage, metric: str, unit: str) -> None:
        try:
            await self._client.post_usage(
                tenant_id=self._tenant_id,
                metric=metric,
                quantity=usage.total_tokens,
                unit=unit,
                idempotency_key=usage.response_id,
                occurred_at=datetime.now(UTC).isoformat(),
                source="publisher",
            )
        except Exception:
            log_json(
                self._logger,
                logging.WARNING,
                "usage_metering_failed",
                metric=metric,
                quantity=usage.total_tokens,
                tenant_id=self._tenant_id,
            )

    async def aclose(self) -> None:
        """Drain everything, then stop the drainer. Never raises."""
        if self._drainer is not None and not self._drainer.done():
            # Wait for all enqueued events (including in-flight batches).
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._queue.join(), timeout=10.0)
            self._drainer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._drainer
            self._drainer = None
        remaining: list[tuple[AIUsage, str, str]] = []
        while True:
            try:
                remaining.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if remaining:
            await asyncio.gather(*(self._post(u, m, un) for u, m, un in remaining))
