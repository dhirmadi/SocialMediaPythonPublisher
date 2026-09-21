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
import uuid
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
        """Bind the meter to one tenant's storage adapter and orchestrator client.

        Args:
            client: Orchestrator client used to POST usage events.
            tenant_id: Tenant the drained ops counts are billed to.
            storage: Managed storage instance whose op counter is drained on flush.
        """
        self._client = client
        self._tenant_id = tenant_id
        self._storage = storage
        self._logger = logging.getLogger("publisher_v2.storage_ops_metering")
        self._periodic_task: asyncio.Task[None] | None = None
        # #92 (decision a): failed batches keep their idempotency key so the
        # retry dedupes correctly upstream. Bounded to avoid unbounded growth
        # during a long orchestrator outage.
        self._pending: list[tuple[str, int, str]] = []  # (idem_key, count, occurred_at)
        self._pending_max = 12

    async def flush(self) -> None:
        """Drain the counter and emit to the orchestrator. Never raises.

        #92 (PERF-4, decision a): each drained batch gets its OWN idempotency
        key (hour prefix + uuid4), so the orchestrator's dedup only protects
        retries of the same batch — previously all flushes in an hour shared
        one key and every flush after the first was silently dropped. Failed
        batches are kept (bounded) and retried with their original key.
        """
        # Retry pending batches first, with their original keys.
        still_pending: list[tuple[str, int, str]] = []
        for idem_key, pending_count, occurred_at in self._pending:
            posted = await self._post_batch(pending_count, idem_key, occurred_at)
            if not posted:
                still_pending.append((idem_key, pending_count, occurred_at))
        self._pending = still_pending

        count = self._storage.drain_ops_count()
        log_json(
            self._logger,
            logging.INFO,
            "storage_ops_flush_attempt",
            drained_count=count,
            tenant_id=self._tenant_id,
        )
        if count <= 0:
            return
        now = datetime.now(UTC)
        idem_key = f"r2ops:{self._tenant_id}:{now.strftime('%Y-%m-%d')}:{now.strftime('%H')}:{uuid.uuid4()}"
        occurred_at = now.isoformat()
        if not await self._post_batch(count, idem_key, occurred_at):
            self._pending.append((idem_key, count, occurred_at))
            if len(self._pending) > self._pending_max:
                dropped_key, dropped_count, _ = self._pending.pop(0)
                log_json(
                    self._logger,
                    logging.WARNING,
                    "storage_ops_pending_batch_dropped",
                    quantity=dropped_count,
                    idempotency_key=dropped_key,
                    tenant_id=self._tenant_id,
                )

    async def _post_batch(self, count: int, idem_key: str, occurred_at: str) -> bool:
        """POST one drained batch. Returns True on success; never raises."""
        try:
            log_json(
                self._logger,
                logging.INFO,
                "storage_ops_flush_posting",
                quantity=count,
                idempotency_key=idem_key,
                tenant_id=self._tenant_id,
            )
            await self._client.post_usage(
                tenant_id=self._tenant_id,
                metric="storage_ops_requests",
                quantity=count,
                unit="requests",
                idempotency_key=idem_key,
                occurred_at=occurred_at,
                source="publisher_storage_ops",
            )
            log_json(
                self._logger,
                logging.INFO,
                "storage_ops_flush_ok",
                quantity=count,
                tenant_id=self._tenant_id,
            )
            return True
        except Exception as exc:
            log_json(
                self._logger,
                logging.WARNING,
                "storage_ops_metering_failed",
                metric="storage_ops_requests",
                quantity=count,
                tenant_id=self._tenant_id,
                error=str(exc),
            )
            return False

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
