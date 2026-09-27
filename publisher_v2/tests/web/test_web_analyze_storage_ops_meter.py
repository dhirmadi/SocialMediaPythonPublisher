"""PUB-047 AC5 (#185): the analyze request path never awaits an orchestrator round-trip.

``WebImageService.analyze_and_caption`` flushes the R2 storage-ops counter in its
``finally``. When the orchestrator is down, ``post_usage`` can hang; the flush must
still return immediately and leave the undelivered batch pending in the meter.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def test_analyze_returns_under_one_second_when_orchestrator_never_responds(
    analyze_service: Callable[..., Any],
) -> None:
    """AC5: a hung ``post_usage`` must not stall analyze; the batch stays pending."""
    from publisher_v2.services.storage_ops_meter import StorageOpsMeter

    service = analyze_service()

    # The fixture's storage is a DropboxStorage, which has no ops counter of its
    # own (that is ManagedStorage-only), so give the meter a non-zero batch to hold.
    service.storage.drain_ops_count = MagicMock(return_value=5)  # type: ignore[attr-defined]

    never_set = asyncio.Event()

    async def _hang(**_kwargs: object) -> None:
        await never_set.wait()

    client = MagicMock()
    client.post_usage = AsyncMock(side_effect=_hang)
    meter = StorageOpsMeter(client=client, tenant_id="tenant-A", storage=service.storage)
    service._storage_ops_meter = meter  # noqa: SLF001 — test injection at the documented seam

    tasks_before = asyncio.all_tasks()
    try:
        with patch("publisher_v2.services.sidecar.generate_and_upload_sidecar", new=AsyncMock(return_value=1.0)):
            try:
                result = await asyncio.wait_for(service.analyze_and_caption("img.jpg"), timeout=1.0)
            except TimeoutError:
                pytest.fail(
                    "analyze_and_caption blocked on the orchestrator round-trip: "
                    "StorageOpsMeter.flush() must enqueue and return, not await post_usage"
                )

        assert result.caption == "fresh AI caption"
        # The batch was drained but never delivered — the meter must still hold it.
        assert meter.pending_batch_count() > 0
    finally:
        # No background drain task may leak into another test (suite runs in random order).
        leaked = asyncio.all_tasks() - tasks_before - {asyncio.current_task()}
        for task in leaked:
            task.cancel()
        if leaked:
            await asyncio.gather(*leaked, return_exceptions=True)
