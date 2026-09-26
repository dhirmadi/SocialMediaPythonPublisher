"""PUB-047 AC5 (#185): the analyze request path never awaits an orchestrator round-trip.

``WebImageService.analyze_and_caption`` flushes the R2 storage-ops counter in its
``finally``. When the orchestrator is down, ``post_usage`` can hang; the flush must
still return immediately and leave the undelivered batch pending in the meter.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from publisher_v2.core.models import ImageAnalysis


def _make_service(monkeypatch: pytest.MonkeyPatch):
    """Build a WebImageService with stubbed storage/AI (mirrors test_web_analyze_sidecar_cache)."""
    # #97 stage 4: env-only configuration (INI removed)
    monkeypatch.setenv("STORAGE_PATHS", '{"root": "/Photos", "archive": "archive"}')
    monkeypatch.setenv("PUBLISHERS", "[]")
    monkeypatch.setenv("OPENAI_SETTINGS", "{}")
    monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch("publisher_v2.services.storage.dropbox.Dropbox"):
        from publisher_v2.web.service import WebImageService

        service = WebImageService()

    service.storage.get_temporary_link = AsyncMock(return_value="http://temp")  # type: ignore[method-assign]
    service.storage.list_images = AsyncMock(return_value=["img.jpg"])  # type: ignore[method-assign]
    service.storage.download_image = AsyncMock(return_value=b"image-bytes")  # type: ignore[method-assign]
    service.storage.download_sidecar_if_exists = AsyncMock(return_value=None)  # type: ignore[method-assign]

    analysis = ImageAnalysis(description="Test", mood="neutral", tags=["t"], nsfw=False, safety_labels=[])
    service.ai_service.analyzer.analyze = AsyncMock(return_value=(analysis, None))  # type: ignore[method-assign, union-attr]
    service.ai_service.create_multi_caption_pair_from_analysis = AsyncMock(  # type: ignore[method-assign, union-attr]
        return_value=({"generic": "fresh AI caption"}, "fresh sd", [], {})  # PUB-051: + angles
    )
    # No real OpenAI call if the multi path ever fails: the caption-only fallback is not mocked
    # otherwise, and would reach the network with the test key.
    service.ai_service.create_caption_from_analysis = AsyncMock(  # type: ignore[method-assign, union-attr]
        side_effect=AssertionError("caption-only fallback ran; the multi-caption path failed")
    )
    return service


async def test_analyze_returns_under_one_second_when_orchestrator_never_responds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC5: a hung ``post_usage`` must not stall analyze; the batch stays pending."""
    from publisher_v2.services.storage_ops_meter import StorageOpsMeter

    service = _make_service(monkeypatch)

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
