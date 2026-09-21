"""PUB-045: Storage ops metering.

Drain the R2 operation counter from ``ManagedStorage`` and emit a single
``storage_ops_requests`` usage event to the orchestrator. Never raises.

Supports periodic background flushing so that ops from grid browsing,
curation, uploads, and deletes are captured even when no analyze/workflow
runs.

PUB-047 (#185): ``flush()`` is fire-and-forget — it drains the counter
synchronously, enqueues the batch, and hands delivery to a background drain
task (mirroring ``services/usage_meter.py``). No request or workflow path ever
awaits an orchestrator round-trip for metering.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from publisher_v2.config.orchestrator_client import RetryConfig
from publisher_v2.utils.logging import log_json

if TYPE_CHECKING:
    from publisher_v2.config.orchestrator_client import OrchestratorClient
    from publisher_v2.services.managed_storage import ManagedStorage

FLUSH_INTERVAL_SECONDS = 300  # 5 minutes
# PUB-047 (#185): one drain attempt is bounded, so a hung orchestrator parks a
# single background task for at most this long rather than forever.
# PUB-061 (#215): the value is an invariant, not a round number — it must sit
# strictly between OrchestratorClient's per-request ``timeout_seconds`` (5.0) and
# ``_ACLOSE_DEADLINE_SECONDS`` (10.0). Drain posts use a single client attempt
# (RetryConfig(max_attempts=1) below), so one full 5.0 s request plus a small
# margin has to fit inside this deadline, and this deadline in turn has to fit
# inside aclose()'s total budget. Do not "simplify" it to 5.0 or raise it to 10.0.
_DRAIN_ATTEMPT_TIMEOUT_SECONDS = 8.0
# PUB-047 (#185): total budget aclose() spends trying to deliver what is left.
_ACLOSE_DEADLINE_SECONDS = 10.0
# PUB-061 (#215): drain posts opt out of the client's inner retry layer.
_SINGLE_ATTEMPT_RETRY = RetryConfig(max_attempts=1)


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
        self._drain_task: asyncio.Task[None] | None = None
        # #92 (decision a): failed batches keep their idempotency key so the
        # retry dedupes correctly upstream. Bounded to avoid unbounded growth
        # during a long orchestrator outage.
        self._pending: list[tuple[str, int, str]] = []  # (idem_key, count, occurred_at)
        self._pending_max = 12

    async def flush(self) -> None:
        """Drain the counter, enqueue the batch, and return. Never raises, never blocks.

        PUB-047 (#185): nothing awaited here can touch the network — delivery is
        owned by the background drain task, so ``flush()`` returns in the same
        call regardless of orchestrator health.

        #92 (PERF-4, decision a): each drained batch gets its OWN idempotency
        key (hour prefix + uuid4), so the orchestrator's dedup only protects
        retries of the same batch. Failed batches are kept (bounded) and
        retried later with their original key.
        """
        self._enqueue_drained_batch()
        self._ensure_drain_task()
        # Yield once so a healthy orchestrator is posted within this call. A hung
        # post_usage suspends the drain task, never this coroutine.
        await asyncio.sleep(0)

    def pending_batch_count(self) -> int:
        """Return how many drained batches are still undelivered."""
        return len(self._pending)

    def _enqueue_drained_batch(self) -> None:
        """Drain the storage counter into ``_pending``. Synchronous and fast."""
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
        self._pending.append((idem_key, count, now.isoformat()))
        while len(self._pending) > self._pending_max:
            dropped_key, dropped_count, _ = self._pending.pop(0)
            log_json(
                self._logger,
                logging.WARNING,
                "storage_ops_pending_batch_dropped",
                quantity=dropped_count,
                idempotency_key=dropped_key,
                tenant_id=self._tenant_id,
            )

    def _ensure_drain_task(self) -> None:
        """Start the background drain task unless one is already running."""
        if self._drain_task is not None and not self._drain_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover — no loop (sync/CLI context)
            return
        self._drain_task = loop.create_task(self._drain_loop())

    async def _drain_loop(self) -> None:
        """Make one pass over the pending queue, then exit.

        Unlike ``UsageMeter._drain_loop`` this exits rather than looping forever;
        ``flush()``/``aclose()`` restart it. A batch leaves ``_pending`` only after
        ``_post_batch`` returns True, so ``pending_batch_count()`` stays accurate
        while an attempt is in flight.
        """
        try:
            await self._drain_pending()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # defensive: a silent death under-bills
            log_json(
                self._logger,
                logging.WARNING,
                "storage_ops_drain_task_failed",
                tenant_id=self._tenant_id,
                pending_batches=len(self._pending),
                error=str(exc),
            )

    async def _drain_pending(self) -> None:
        """Attempt each batch pending at entry exactly once, then return.

        One pass over a snapshot of ``_pending``: a batch whose attempt fails is kept
        (with its original idempotency key) and the pass moves on to the next batch, so a
        permanently failing batch cannot head-of-line-block the ones behind it. The pass
        never restarts while ``_pending`` is non-empty, which is what stops a dead
        orchestrator from being hot-spun; the next ``flush()``/``aclose()`` retries.
        """
        for idem_key, count, occurred_at in list(self._pending):
            try:
                posted = await asyncio.wait_for(
                    self._post_batch(count, idem_key, occurred_at),
                    timeout=_DRAIN_ATTEMPT_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                log_json(
                    self._logger,
                    logging.WARNING,
                    "storage_ops_drain_attempt_timeout",
                    quantity=count,
                    idempotency_key=idem_key,
                    tenant_id=self._tenant_id,
                )
                posted = False
            if not posted:
                # Keep the batch (with its key) for the next run and try the next one.
                continue
            self._pending = [batch for batch in self._pending if batch[0] != idem_key]

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
                # PUB-061 (#215): the meter is already the retry layer — a failed
                # batch keeps its idempotency key and is retried by the next
                # flush()/aclose(). Stacking the client's three attempts on top is
                # what pushed one drain attempt past the deadline wrapping it.
                retry=_SINGLE_ATTEMPT_RETRY,
            )
            log_json(
                self._logger,
                logging.INFO,
                "storage_ops_flush_ok",
                quantity=count,
                tenant_id=self._tenant_id,
            )
            return True
        except asyncio.CancelledError:
            raise
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
        """Cancel the periodic task and drain what is left. Never raises."""
        await self.aclose()

    async def aclose(self) -> None:
        """Stop the background tasks and drain remaining batches under a deadline.

        Mirrors ``UsageMeter.aclose()``. Never raises; an undrained queue is
        surfaced as ``storage_ops_meter_undrained_queue`` rather than silently
        dropped, because a lost batch under-bills the tenant.
        """
        await self._cancel_task(self._periodic_task)
        self._periodic_task = None
        await self._cancel_task(self._drain_task)
        self._drain_task = None

        self._enqueue_drained_batch()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._drain_pending(), timeout=_ACLOSE_DEADLINE_SECONDS)
        if self._pending:
            log_json(
                self._logger,
                logging.WARNING,
                "storage_ops_meter_undrained_queue",
                remaining=len(self._pending),
                tenant_id=self._tenant_id,
            )

    @staticmethod
    async def _cancel_task(task: asyncio.Task[None] | None) -> None:
        """Cancel a background task and await its completion. Never raises."""
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    async def _periodic_loop(self) -> None:
        """Flush every FLUSH_INTERVAL_SECONDS until cancelled."""
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
            await self.flush()
