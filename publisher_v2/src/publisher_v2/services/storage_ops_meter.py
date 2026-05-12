"""PUB-045: Storage ops metering.

Drain the R2 operation counter from ``ManagedStorage`` and emit a single
``storage_ops_requests`` usage event to the orchestrator. Never raises.

Supports periodic background flushing so that ops from grid browsing,
curation, uploads, and deletes are captured even when no analyze/workflow
runs.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from publisher_v2.utils.logging import log_json

if TYPE_CHECKING:
    from publisher_v2.config.orchestrator_client import OrchestratorClient
    from publisher_v2.services.managed_storage import ManagedStorage

FLUSH_INTERVAL_SECONDS = 300  # 5 minutes


class StorageOpsMeter:
    """Emit aggregated R2 storage ops counts to the orchestrator billing endpoint."""

    def __init__(
        self,
        client: OrchestratorClient,
        tenant_id: str,
        storage: ManagedStorage,
    ) -> None:
        self._client = client
        self._tenant_id = tenant_id
        self._storage = storage
        self._logger = logging.getLogger("publisher_v2.storage_ops_metering")
        self._periodic_task: asyncio.Task[None] | None = None

    async def flush(self) -> None:
        """Drain the counter and emit to the orchestrator. Never raises."""
        count = self._storage.drain_ops_count()
        if count <= 0:
            return
        try:
            now = datetime.now(UTC)
            await self._client.post_usage(
                tenant_id=self._tenant_id,
                metric="storage_ops_requests",
                quantity=count,
                unit="requests",
                idempotency_key=f"r2ops:{self._tenant_id}:{now.strftime('%Y-%m-%d')}:{now.strftime('%H')}",
                occurred_at=now.isoformat(),
                source="publisher_storage_ops",
            )
        except Exception:
            log_json(
                self._logger,
                logging.WARNING,
                "storage_ops_metering_failed",
                metric="storage_ops_requests",
                quantity=count,
                tenant_id=self._tenant_id,
            )

    def start_periodic_flush(self) -> None:
        """Start a background task that flushes every FLUSH_INTERVAL_SECONDS.

        Safe to call outside of an async context — silently skips if no event
        loop is running (e.g. during tests or CLI mode).
        """
        if self._periodic_task is not None and not self._periodic_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._periodic_task = loop.create_task(self._periodic_loop())
        except RuntimeError:
            pass

    async def stop_periodic_flush(self) -> None:
        """Cancel the periodic task and do a final flush."""
        if self._periodic_task is not None and not self._periodic_task.done():
            self._periodic_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._periodic_task
            self._periodic_task = None
        await self.flush()

    async def _periodic_loop(self) -> None:
        """Flush every FLUSH_INTERVAL_SECONDS until cancelled."""
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
            await self.flush()
