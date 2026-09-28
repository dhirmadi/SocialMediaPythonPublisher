"""PUB-045: Tests for StorageOpsMeter."""

from __future__ import annotations

import asyncio
import contextlib
import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


async def _hang_forever(**_kwargs: Any) -> None:
    """Stand-in for an orchestrator POST that never answers."""
    await asyncio.Event().wait()


async def _settle(task: asyncio.Task[None] | None, tries: int = 200) -> None:
    """Let a background drain task reach completion without sleeping for real timeouts."""
    for _ in range(tries):
        if task is None or task.done():
            break
        await asyncio.sleep(0.005)
    if task is not None and not task.done():  # pragma: no cover - safety net
        task.cancel()
        with contextlib.suppress(BaseException):
            await task


def _build_meter(count: int = 0):
    from publisher_v2.services.storage_ops_meter import StorageOpsMeter

    client = MagicMock()
    client.post_usage = AsyncMock(return_value={"ok": True})
    storage = MagicMock()
    storage.drain_ops_count = MagicMock(return_value=count)
    meter = StorageOpsMeter(client=client, tenant_id="tenant-A", storage=storage)
    return meter, client, storage


class TestStorageOpsMeter:
    async def test_flush_calls_post_usage_with_correct_args(self) -> None:
        """AC-B2: flush POSTs with correct metric/unit/source/quantity."""
        meter, client, storage = _build_meter(count=42)

        await meter.flush()

        storage.drain_ops_count.assert_called_once()
        client.post_usage.assert_awaited_once()
        kwargs = client.post_usage.await_args.kwargs
        assert kwargs["tenant_id"] == "tenant-A"
        assert kwargs["metric"] == "storage_ops_requests"
        assert kwargs["unit"] == "requests"
        assert kwargs["quantity"] == 42
        assert kwargs["source"] == "publisher_storage_ops"

    async def test_idempotency_key_format_hourly_window(self) -> None:
        """AC-B3, amended by #92: hour-prefixed key plus a per-flush uuid so
        multiple flushes within one hour are all credited."""
        meter, client, _ = _build_meter(count=7)

        await meter.flush()

        kwargs = client.post_usage.await_args.kwargs
        key = kwargs["idempotency_key"]
        assert re.match(r"^r2ops:tenant-A:\d{4}-\d{2}-\d{2}:\d{2}:[0-9a-f-]{36}$", key), f"Bad key: {key}"

    async def test_flush_skips_post_when_count_zero(self) -> None:
        """AC-B4: no POST when drain returns 0."""
        meter, client, storage = _build_meter(count=0)

        await meter.flush()

        storage.drain_ops_count.assert_called_once()
        client.post_usage.assert_not_awaited()

    async def test_flush_catches_exception_and_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC-B5: when post_usage raises, flush catches it and logs storage_ops_metering_failed."""
        import logging

        meter, client, _ = _build_meter(count=10)
        client.post_usage.side_effect = RuntimeError("boom")

        caplog.set_level(logging.WARNING, logger="publisher_v2.storage_ops_metering")
        await meter.flush()  # must not raise

        joined = " ".join(rec.getMessage() for rec in caplog.records)
        assert "storage_ops_metering_failed" in joined

    async def test_flush_never_raises(self) -> None:
        """AC-B6: any exception from post_usage is swallowed."""
        meter, client, _ = _build_meter(count=1)
        client.post_usage.side_effect = Exception("anything")

        # Should not raise
        await meter.flush()


class TestPerFlushIdempotencyKeys:
    """#92 (PERF-4, decision a): every flush gets its own key; retries reuse it."""

    async def test_two_flushes_same_hour_use_distinct_keys(self) -> None:
        meter, client, storage = _build_meter(count=5)
        storage.drain_ops_count = MagicMock(side_effect=[5, 7])

        await meter.flush()
        await meter.flush()

        keys = [call.kwargs["idempotency_key"] for call in client.post_usage.await_args_list]
        assert len(keys) == 2
        assert keys[0] != keys[1]
        for key in keys:
            assert re.match(r"^r2ops:tenant-A:\d{4}-\d{2}-\d{2}:\d{2}:[0-9a-f-]{36}$", key)

    async def test_failed_flush_retries_same_batch_with_same_key(self) -> None:
        meter, client, storage = _build_meter()
        storage.drain_ops_count = MagicMock(side_effect=[5, 0])
        client.post_usage = AsyncMock(side_effect=[RuntimeError("boom"), {"ok": True}])

        await meter.flush()  # fails — batch (5) kept pending with its key
        await meter.flush()  # drains 0, retries the pending batch

        calls = client.post_usage.await_args_list
        assert len(calls) == 2
        assert calls[0].kwargs["idempotency_key"] == calls[1].kwargs["idempotency_key"]
        assert calls[0].kwargs["quantity"] == 5
        assert calls[1].kwargs["quantity"] == 5

    async def test_no_drained_count_is_lost_across_failures(self) -> None:
        meter, client, storage = _build_meter()
        storage.drain_ops_count = MagicMock(side_effect=[5, 7, 0])
        client.post_usage = AsyncMock(side_effect=[RuntimeError("boom"), {"ok": True}, {"ok": True}])

        await meter.flush()  # 5 fails, pending
        await meter.flush()  # retries 5 (ok), posts 7 (ok)
        await meter.flush()  # nothing left

        quantities = sorted(call.kwargs["quantity"] for call in client.post_usage.await_args_list)
        assert quantities == [5, 5, 7]


class TestDrainLoopBackoffSemantics:
    """PUB-047 (#185): one attempt per batch, exit on first failure, keep the key."""

    async def test_drain_loop_exits_on_first_failure_without_hot_spinning(self) -> None:
        meter, client, storage = _build_meter()
        storage.drain_ops_count = MagicMock(side_effect=[9, 0, 0, 0])
        client.post_usage = AsyncMock(side_effect=RuntimeError("orchestrator down"))

        await meter.flush()

        # The failed batch stays pending with its original key ...
        assert len(meter._pending) == 1
        original_key = meter._pending[0][0]
        assert meter._pending[0][1] == 9

        # ... and the drain task has exited rather than retrying in a tight loop.
        for _ in range(10):
            await asyncio.sleep(0)
        assert meter._drain_task is not None
        assert meter._drain_task.done()
        assert client.post_usage.await_count == 1

        # The next flush retries the same batch under the same idempotency key.
        client.post_usage.side_effect = None
        client.post_usage.return_value = {"ok": True}
        await meter.flush()
        assert client.post_usage.await_count == 2
        assert client.post_usage.await_args.kwargs["idempotency_key"] == original_key
        assert len(meter._pending) == 0

    async def test_drain_attempt_timeout_is_bounded_and_logged(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A _post_batch that outlives _DRAIN_ATTEMPT_TIMEOUT_SECONDS logs and keeps the batch."""
        import logging

        from publisher_v2.services import storage_ops_meter as mod

        monkeypatch.setattr(mod, "_DRAIN_ATTEMPT_TIMEOUT_SECONDS", 0.01)
        meter, client, storage = _build_meter()
        storage.drain_ops_count = MagicMock(side_effect=[11, 0, 0])
        client.post_usage = AsyncMock(side_effect=_hang_forever)

        caplog.set_level(logging.WARNING, logger="publisher_v2.storage_ops_metering")
        await meter.flush()
        await _settle(meter._drain_task)

        joined = " ".join(rec.getMessage() for rec in caplog.records)
        assert "storage_ops_drain_attempt_timeout" in joined
        assert len(meter._pending) == 1
        assert meter._pending[0][1] == 11


class TestAclose:
    """PUB-047 (#185): aclose() stops background work and drains under a bounded deadline."""

    async def test_aclose_cancels_periodic_task_and_drains_pending(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from publisher_v2.services import storage_ops_meter as mod

        monkeypatch.setattr(mod, "FLUSH_INTERVAL_SECONDS", 3600)
        meter, client, storage = _build_meter()
        storage.drain_ops_count = MagicMock(side_effect=[0, 13, 0])
        client.post_usage = AsyncMock(side_effect=[RuntimeError("boom"), {"ok": True}])

        meter.start_periodic_flush()
        periodic = meter._periodic_task
        assert periodic is not None

        await meter.flush()  # drains 0 -> nothing pending
        storage.drain_ops_count = MagicMock(return_value=13)
        await meter.flush()  # drains 13, post fails -> stays pending
        assert len(meter._pending) == 1

        storage.drain_ops_count = MagicMock(return_value=0)
        await meter.aclose()

        assert periodic.cancelled() or periodic.done()
        assert meter._periodic_task is None
        assert meter._drain_task is None
        assert len(meter._pending) == 0
        assert client.post_usage.await_count == 2

    async def test_aclose_deadline_logs_undrained_queue_and_never_raises(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        from publisher_v2.services import storage_ops_meter as mod

        monkeypatch.setattr(mod, "_ACLOSE_DEADLINE_SECONDS", 0.01)
        meter, client, storage = _build_meter()
        storage.drain_ops_count = MagicMock(return_value=0)
        client.post_usage = AsyncMock(side_effect=_hang_forever)
        meter._pending.append(("r2ops:tenant-A:stuck", 17, "2026-01-01T00:00:00+00:00"))

        caplog.set_level(logging.WARNING, logger="publisher_v2.storage_ops_metering")
        await meter.aclose()  # must not raise despite the hung post

        joined = " ".join(rec.getMessage() for rec in caplog.records)
        assert "storage_ops_meter_undrained_queue" in joined
        undrained = [rec for rec in caplog.records if "storage_ops_meter_undrained_queue" in rec.getMessage()]
        assert '"remaining": 1' in undrained[-1].getMessage()
        assert len(meter._pending) == 1

    async def test_aclose_stops_periodic_flush_and_posts_final_drain(self) -> None:
        """#286: ``stop_periodic_flush`` (a pure alias) is gone; ``aclose`` is the one shutdown path."""
        meter, client, storage = _build_meter()
        storage.drain_ops_count = MagicMock(return_value=4)
        meter.start_periodic_flush()

        await meter.aclose()

        assert meter._periodic_task is None
        assert len(meter._pending) == 0
        client.post_usage.assert_awaited_once()
        assert client.post_usage.await_args.kwargs["quantity"] == 4

    async def test_aclose_is_idempotent(self) -> None:
        meter, client, storage = _build_meter()
        storage.drain_ops_count = MagicMock(return_value=0)

        await meter.aclose()
        await meter.aclose()

        assert len(meter._pending) == 0
        client.post_usage.assert_not_awaited()


class TestCancelTask:
    """PUB-047 (#185): _cancel_task never raises, whatever the task's state."""

    async def test_cancel_task_none_is_a_noop(self) -> None:
        from publisher_v2.services.storage_ops_meter import StorageOpsMeter

        await StorageOpsMeter._cancel_task(None)

    async def test_cancel_task_already_done_is_a_noop(self) -> None:
        from publisher_v2.services.storage_ops_meter import StorageOpsMeter

        async def _done() -> None:
            return None

        task = asyncio.ensure_future(_done())
        await task
        await StorageOpsMeter._cancel_task(task)
        assert not task.cancelled()

    async def test_cancel_task_cancels_a_running_task(self) -> None:
        from publisher_v2.services.storage_ops_meter import StorageOpsMeter

        async def _forever() -> None:
            await asyncio.Event().wait()

        task = asyncio.ensure_future(_forever())
        await asyncio.sleep(0)

        await StorageOpsMeter._cancel_task(task)

        assert task.done()
        assert task.cancelled()

    async def test_cancel_task_swallows_task_exception(self) -> None:
        from publisher_v2.services.storage_ops_meter import StorageOpsMeter

        async def _boom() -> None:
            await asyncio.sleep(0)
            raise RuntimeError("boom")

        task = asyncio.ensure_future(_boom())
        await StorageOpsMeter._cancel_task(task)  # must not raise
        assert task.done()


class TestPeriodicFlush:
    """PUB-045/PUB-047: the periodic loop keeps metering alive without analyze traffic."""

    async def test_periodic_loop_flushes_on_interval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from publisher_v2.services import storage_ops_meter as mod

        monkeypatch.setattr(mod, "FLUSH_INTERVAL_SECONDS", 0.01)
        meter, client, storage = _build_meter()
        storage.drain_ops_count = MagicMock(return_value=3)

        meter.start_periodic_flush()
        assert meter._periodic_task is not None
        for _ in range(100):
            if client.post_usage.await_count >= 1:
                break
            await asyncio.sleep(0.01)

        await meter.aclose()

        assert client.post_usage.await_count >= 1
        assert client.post_usage.await_args.kwargs["quantity"] == 3
        assert client.post_usage.await_args.kwargs["metric"] == "storage_ops_requests"

    async def test_start_periodic_flush_is_idempotent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from publisher_v2.services import storage_ops_meter as mod

        monkeypatch.setattr(mod, "FLUSH_INTERVAL_SECONDS", 3600)
        meter, _client, storage = _build_meter()
        storage.drain_ops_count = MagicMock(return_value=0)

        meter.start_periodic_flush()
        first = meter._periodic_task
        meter.start_periodic_flush()
        assert meter._periodic_task is first

        await meter.aclose()

    def test_start_periodic_flush_without_event_loop_is_silent(self) -> None:
        """Sync/CLI context: no running loop must not raise and must not create a task."""
        meter, _client, _storage = _build_meter()

        meter.start_periodic_flush()

        assert meter._periodic_task is None


class TestPendingQueueBounds:
    """#92 (decision a): the retry queue is bounded; the oldest batch is dropped loudly."""

    async def test_oldest_batch_dropped_when_pending_cap_exceeded(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        from publisher_v2.services import storage_ops_meter as mod

        meter, client, storage = _build_meter()
        storage.drain_ops_count = MagicMock(return_value=1)
        client.post_usage = AsyncMock(side_effect=_hang_forever)

        caplog.set_level(logging.WARNING, logger="publisher_v2.storage_ops_metering")
        for _ in range(mod._PENDING_MAX + 2):
            meter._enqueue_drained_batch()

        assert len(meter._pending) == mod._PENDING_MAX
        joined = " ".join(rec.getMessage() for rec in caplog.records)
        assert "storage_ops_pending_batch_dropped" in joined
        meter._pending.clear()

    async def test_flush_does_not_start_a_second_drain_task(self) -> None:
        meter, client, storage = _build_meter()
        storage.drain_ops_count = MagicMock(return_value=2)
        client.post_usage = AsyncMock(side_effect=_hang_forever)

        await meter.flush()
        first = meter._drain_task
        assert first is not None and not first.done()

        await meter.flush()

        assert meter._drain_task is first
        assert client.post_usage.await_count == 1
        await meter._cancel_task(meter._drain_task)
        meter._pending.clear()

    async def test_drain_task_cancellation_is_not_reported_as_failure(self) -> None:
        """A cancelled drain task ends cancelled; nothing swallows the cancellation."""
        meter, client, storage = _build_meter()
        storage.drain_ops_count = MagicMock(return_value=6)
        client.post_usage = AsyncMock(side_effect=_hang_forever)

        await meter.flush()
        task = meter._drain_task
        assert task is not None

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert task.cancelled()
        meter._pending.clear()


class TestSlowButAliveOrchestrator:
    """PUB-061 (#215): a slow-but-alive orchestrator must be delivered to, not timed out.

    All timings are scaled by ``_SCALE`` so the test runs in milliseconds while still
    encoding the real relationship: a ~6 s response (1.2x the client's 5.0 s per-request
    timeout) must fit inside ``_DRAIN_ATTEMPT_TIMEOUT_SECONDS``.
    """

    _SCALE = 0.01

    @staticmethod
    def _client_request_timeout() -> float:
        import inspect

        from publisher_v2.config.orchestrator_client import OrchestratorClient

        default = inspect.signature(OrchestratorClient.__init__).parameters["timeout_seconds"].default
        return float(default)

    async def test_slow_but_alive_post_usage_batch_is_delivered_not_timed_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PUB-061 AC2: a post that answers just after one client request timeout still delivers."""
        from publisher_v2.services import storage_ops_meter as mod

        scale = self._SCALE
        # A slow-but-alive orchestrator: ~6 s, i.e. 1.2x the client's per-request timeout.
        slow_response_seconds = 1.2 * self._client_request_timeout() * scale
        # Scale the production deadline by the same factor — this is what makes the test
        # track the real constant instead of a value the test itself chose.
        monkeypatch.setattr(mod, "_DRAIN_ATTEMPT_TIMEOUT_SECONDS", mod._DRAIN_ATTEMPT_TIMEOUT_SECONDS * scale)

        meter, client, storage = _build_meter()
        storage.drain_ops_count = MagicMock(side_effect=[23, 0, 0])

        async def _slow_ok(**_kwargs: Any) -> dict[str, bool]:
            await asyncio.sleep(slow_response_seconds)
            return {"ok": True}

        client.post_usage = AsyncMock(side_effect=_slow_ok)

        await meter.flush()
        await _settle(meter._drain_task)

        assert client.post_usage.await_count == 1
        assert len(meter._pending) == 0, (
            "slow-but-alive orchestrator batch was dropped by the drain deadline "
            f"(deadline {mod._DRAIN_ATTEMPT_TIMEOUT_SECONDS}s vs response {slow_response_seconds}s, scaled)"
        )

    def test_drain_attempt_timeout_exceeds_client_timeout_and_fits_aclose_budget(self) -> None:
        """PUB-061 AC4: one full client attempt fits inside the drain deadline, which fits aclose()."""
        from publisher_v2.services import storage_ops_meter as mod

        client_timeout = self._client_request_timeout()
        assert client_timeout < mod._DRAIN_ATTEMPT_TIMEOUT_SECONDS, (
            f"drain deadline {mod._DRAIN_ATTEMPT_TIMEOUT_SECONDS} must exceed the client's "
            f"per-request timeout {client_timeout}"
        )
        assert mod._DRAIN_ATTEMPT_TIMEOUT_SECONDS < mod._ACLOSE_DEADLINE_SECONDS

    async def test_drain_post_uses_single_attempt_retry_override(self) -> None:
        """PUB-061 AC1/decision: drain posts opt out of the client's inner retry layer."""
        meter, client, storage = _build_meter()
        storage.drain_ops_count = MagicMock(side_effect=[5, 0])

        await meter.flush()
        await _settle(meter._drain_task)

        kwargs = client.post_usage.await_args.kwargs
        assert "retry" in kwargs, "drain post must pass a per-call retry override"
        assert kwargs["retry"].max_attempts == 1


class TestSharedBackgroundPlumbing:
    """PUB-084 AC14 (#286): one shared ``_spawn_if_loop``, no alias/test-only wrappers, module constant cap."""

    def test_spawn_if_loop_without_running_loop_is_noop(self) -> None:
        """AC14: with no running loop the shared helper schedules nothing, returns None and closes the
        coroutine (so no "coroutine was never awaited" warning); both meters use that one helper."""
        import warnings

        from publisher_v2.services import storage_ops_meter, usage_meter
        from publisher_v2.services.usage_meter import _spawn_if_loop

        ran: list[int] = []

        async def _work() -> None:
            ran.append(1)

        coro = _work()
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            result = _spawn_if_loop(coro)

        assert result is None
        assert coro.cr_frame is None, "the unscheduled coroutine must be closed, not leaked"
        assert ran == []
        assert storage_ops_meter._spawn_if_loop is usage_meter._spawn_if_loop, (
            "both meters must schedule background work through the one shared _spawn_if_loop"
        )

    async def test_spawn_if_loop_with_running_loop_returns_the_task(self) -> None:
        """AC14 counterpart: inside a running loop the helper schedules the coroutine and returns its task."""
        from publisher_v2.services.usage_meter import _spawn_if_loop

        ran: list[int] = []

        async def _work() -> None:
            ran.append(1)

        task = _spawn_if_loop(_work())

        assert isinstance(task, asyncio.Task)
        await task
        assert ran == [1]

    def test_storage_ops_meter_has_no_alias_or_test_only_wrappers(self) -> None:
        """#286: ``stop_periodic_flush`` (alias of ``aclose``), ``pending_batch_count`` (test-only) and the
        ``_drain_loop`` catch-all around ``_drain_pending`` are deleted."""
        from publisher_v2.services.storage_ops_meter import StorageOpsMeter

        leftovers = [
            name
            for name in ("stop_periodic_flush", "pending_batch_count", "_drain_loop")
            if hasattr(StorageOpsMeter, name)
        ]
        assert leftovers == []

    def test_pending_cap_is_a_module_constant(self) -> None:
        """#286: the pending-batch cap is a module constant, not a per-instance attribute nobody overrides."""
        from publisher_v2.services import storage_ops_meter as mod

        meter, _client, _storage = _build_meter()

        assert getattr(mod, "_PENDING_MAX", None) == 12
        assert not hasattr(meter, "_pending_max")
