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
        """AC-B3: idempotency key matches r2ops:{tenant}:{yyyy-mm-dd}:{HH}."""
        meter, client, _ = _build_meter(count=7)

        await meter.flush()

        kwargs = client.post_usage.await_args.kwargs
        key = kwargs["idempotency_key"]
        assert re.match(r"^r2ops:tenant-A:\d{4}-\d{2}-\d{2}:\d{2}$", key), f"Bad key: {key}"

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
