"""REL-4 (#86): tenant-safe, TTL-bounded per-instance ManagedStorage thumbnail cache."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from publisher_v2.config.schema import ManagedStorageConfig
from publisher_v2.services.managed_storage import ManagedStorage
from publisher_v2.services.storage_protocol import FileMetadata


def _png(color: str) -> bytes:
    buf = io.BytesIO()
    with Image.new("RGB", (100, 60), color=color) as img:
        img.save(buf, format="PNG")
    return buf.getvalue()


def _storage(bucket: str, image: bytes, etag: str = "etag-1") -> ManagedStorage:
    cfg = ManagedStorageConfig(
        access_key_id="k",
        secret_access_key="s",
        endpoint_url="https://example.r2.local",
        bucket=bucket,
        region="auto",
    )
    storage = ManagedStorage(cfg)
    storage.download_image = AsyncMock(return_value=image)  # type: ignore[method-assign]
    storage.get_file_metadata = AsyncMock(
        return_value=FileMetadata(file_id="k", revision=etag, modified_at=None, size=None)
    )  # type: ignore[method-assign]
    return storage


async def test_same_key_different_buckets_never_share_thumbnails() -> None:
    red = _storage("bucket-a", _png("red"))
    blue = _storage("bucket-b", _png("blue"))

    thumb_a = await red.get_thumbnail("/Photos", "img.jpg")
    thumb_b = await blue.get_thumbnail("/Photos", "img.jpg")

    assert thumb_a != thumb_b
    # Cached lookups stay isolated too.
    assert await red.get_thumbnail("/Photos", "img.jpg") == thumb_a
    assert await blue.get_thumbnail("/Photos", "img.jpg") == thumb_b


async def test_cache_hit_skips_download() -> None:
    storage = _storage("bucket-a", _png("red"))
    await storage.get_thumbnail("/Photos", "img.jpg")
    await storage.get_thumbnail("/Photos", "img.jpg")
    assert storage.download_image.await_count == 1  # type: ignore[union-attr]


async def test_reupload_with_new_etag_regenerates() -> None:
    storage = _storage("bucket-a", _png("red"), etag="etag-1")
    first = await storage.get_thumbnail("/Photos", "img.jpg")

    storage.download_image = AsyncMock(return_value=_png("green"))  # type: ignore[method-assign]
    storage.get_file_metadata = AsyncMock(
        return_value=FileMetadata(file_id="k", revision="etag-2", modified_at=None, size=None)
    )  # type: ignore[method-assign]
    second = await storage.get_thumbnail("/Photos", "img.jpg")

    assert first != second


async def test_ttl_expiry_regenerates(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_now = {"t": 1000.0}
    monkeypatch.setattr("publisher_v2.services.managed_storage.time.time", lambda: fake_now["t"])
    monkeypatch.setenv("WEB_THUMBNAIL_CACHE_TTL_SECONDS", "900")

    storage = _storage("bucket-a", _png("red"))
    await storage.get_thumbnail("/Photos", "img.jpg")
    assert storage.download_image.await_count == 1  # type: ignore[union-attr]

    fake_now["t"] += 901
    await storage.get_thumbnail("/Photos", "img.jpg")
    assert storage.download_image.await_count == 2  # type: ignore[union-attr]


async def test_byte_budget_evicts_oldest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_THUMBNAIL_CACHE_MAX_BYTES", "1")  # every entry over budget
    storage = _storage("bucket-a", _png("red"))
    await storage.get_thumbnail("/Photos", "img.jpg")
    await storage.get_thumbnail("/Photos", "img.jpg")
    # Nothing can stay cached under a 1-byte budget → downloads every time.
    assert storage.download_image.await_count == 2  # type: ignore[union-attr]
