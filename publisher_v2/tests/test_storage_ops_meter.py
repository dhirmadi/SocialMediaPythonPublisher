"""PUB-045: Tests for StorageOpsMeter."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock

import pytest


def _build_meter(count: int = 0):
    from publisher_v2.services.storage_ops_meter import StorageOpsMeter

    client = MagicMock()
    client.post_usage = AsyncMock(return_value={"ok": True})
    storage = MagicMock()
    storage.drain_ops_count = MagicMock(return_value=count)
    meter = StorageOpsMeter(client=client, tenant_id="tenant-A", storage=storage)
    return meter, client, storage


class TestStorageOpsMeter:
    def test_storage_ops_meter_exists_with_flush_method(self) -> None:
        """AC-B1: class exists and exposes flush()."""
        from publisher_v2.services.storage_ops_meter import StorageOpsMeter

        assert hasattr(StorageOpsMeter, "flush")

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
