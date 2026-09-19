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


async def test_reupload_with_new_etag_regenerates_after_the_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """#140 changed when the ETag is consulted: on revalidation, not on every request.

    Within the TTL a cache hit costs zero storage ops, so a silent re-upload is
    served from cache until the entry expires (or the upload/move path calls
    ``invalidate_thumbnail``, covered separately).
    """
    fake_now = {"t": 1000.0}
    monkeypatch.setattr("publisher_v2.services.managed_storage.time.time", lambda: fake_now["t"])
    monkeypatch.setenv("WEB_THUMBNAIL_CACHE_TTL_SECONDS", "900")
    storage = _storage("bucket-a", _png("red"), etag="etag-1")
    first = await storage.get_thumbnail("/Photos", "img.jpg")

    storage.download_image = AsyncMock(return_value=_png("green"))  # type: ignore[method-assign]
    storage.get_file_metadata = AsyncMock(
        return_value=FileMetadata(file_id="k", revision="etag-2", modified_at=None, size=None)
    )  # type: ignore[method-assign]
    assert await storage.get_thumbnail("/Photos", "img.jpg") == first  # still inside the TTL

    fake_now["t"] += 901
    second = await storage.get_thumbnail("/Photos", "img.jpg")

    assert first != second


async def test_ttl_expiry_revalidates_and_keeps_an_unchanged_thumbnail(monkeypatch: pytest.MonkeyPatch) -> None:
    """#140: past the TTL the ETag is re-checked; unchanged objects are not downloaded again.

    Before #140 the expiry path always re-downloaded. Revalidating is strictly
    cheaper and cannot serve stale bytes, since a differing ETag still regenerates.
    """
    fake_now = {"t": 1000.0}
    monkeypatch.setattr("publisher_v2.services.managed_storage.time.time", lambda: fake_now["t"])
    monkeypatch.setenv("WEB_THUMBNAIL_CACHE_TTL_SECONDS", "900")

    storage = _storage("bucket-a", _png("red"))
    await storage.get_thumbnail("/Photos", "img.jpg")
    assert storage.download_image.await_count == 1  # type: ignore[union-attr]

    fake_now["t"] += 901
    await storage.get_thumbnail("/Photos", "img.jpg")
    assert storage.download_image.await_count == 1  # type: ignore[union-attr]
    assert storage.get_file_metadata.await_count == 2  # type: ignore[union-attr]

    storage.get_file_metadata = AsyncMock(
        return_value=FileMetadata(file_id="k", revision="etag-9", modified_at=None, size=None)
    )  # type: ignore[method-assign]
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


# --- #140: a cache hit must cost zero storage ops ---


class _CountingS3:
    """Counts the boto3 calls ManagedStorage makes (the billed R2 ops)."""

    def __init__(self, body: bytes, etag: str = '"etag-1"') -> None:
        self.body = body
        self.etag = etag
        self.head_calls = 0
        self.get_calls = 0

    def head_object(self, **_kwargs: object) -> dict[str, object]:
        self.head_calls += 1
        return {"ETag": self.etag, "ContentLength": len(self.body), "LastModified": None}

    def get_object(self, **_kwargs: object) -> dict[str, object]:
        self.get_calls += 1
        return {"Body": io.BytesIO(self.body), "ETag": self.etag}

    def put_object(self, **_kwargs: object) -> dict[str, object]:
        return {}

    def delete_object(self, **_kwargs: object) -> dict[str, object]:
        return {}

    def copy_object(self, **_kwargs: object) -> dict[str, object]:
        return {}

    def close(self) -> None:
        return None


@pytest.fixture
def counting_storage() -> tuple[ManagedStorage, _CountingS3]:
    from unittest.mock import MagicMock, patch

    client = _CountingS3(_png("red"))
    cfg = ManagedStorageConfig(
        access_key_id="k",
        secret_access_key="s",
        endpoint_url="https://example.r2.local",
        bucket="bucket-a",
        region="auto",
    )
    with patch("publisher_v2.services.managed_storage.boto3") as boto:
        boto.client = MagicMock(return_value=client)
        storage = ManagedStorage(cfg)
    return storage, client


async def test_cache_hit_within_ttl_issues_no_storage_ops(counting_storage, monkeypatch: pytest.MonkeyPatch) -> None:
    """#140 AC: the second thumbnail request inside the TTL must bill nothing."""
    storage, client = counting_storage
    monkeypatch.setenv("WEB_THUMBNAIL_CACHE_TTL_SECONDS", "900")
    await storage.get_thumbnail("/Photos", "img.jpg")
    ops_after_first = (client.head_calls, client.get_calls)

    await storage.get_thumbnail("/Photos", "img.jpg")

    assert (client.head_calls, client.get_calls) == ops_after_first


async def test_expired_entry_revalidates_with_one_head_and_no_download(
    counting_storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Past the TTL the ETag is re-checked; an unchanged object must not be downloaded again."""
    storage, client = counting_storage
    monkeypatch.setenv("WEB_THUMBNAIL_CACHE_TTL_SECONDS", "0")
    first = await storage.get_thumbnail("/Photos", "img.jpg")
    heads, gets = client.head_calls, client.get_calls

    second = await storage.get_thumbnail("/Photos", "img.jpg")

    assert second == first
    assert client.head_calls == heads + 1
    assert client.get_calls == gets


async def test_invalidated_key_regenerates_on_the_next_request(counting_storage) -> None:
    """An upload/move through the library invalidates the entry directly (#140)."""
    storage, client = counting_storage
    first = await storage.get_thumbnail("/Photos", "img.jpg")
    gets = client.get_calls

    storage.invalidate_thumbnail("Photos/img.jpg")
    client.body = _png("blue")
    client.etag = '"etag-2"'
    regenerated = await storage.get_thumbnail("/Photos", "img.jpg")

    assert client.get_calls == gets + 1
    assert regenerated != first


# --- #140: every write path invalidates, not just the library router ---


async def _cached_thumb(storage: ManagedStorage) -> bytes:
    return await storage.get_thumbnail("/Photos", "img.jpg")


@pytest.mark.parametrize(
    "write",
    [
        pytest.param(lambda s: s.put_object("Photos/img.jpg", b"x", "image/jpeg"), id="put_object"),
        pytest.param(lambda s: s.delete_object("Photos/img.jpg"), id="delete_object"),
        pytest.param(lambda s: s.move_object("Photos/img.jpg", "Photos/archive/img.jpg"), id="move_object"),
        pytest.param(lambda s: s.archive_image("/Photos", "img.jpg", "/Photos/archive"), id="archive_image"),
        pytest.param(lambda s: s.move_image_with_sidecars("/Photos", "img.jpg", "keep"), id="curation_move"),
        pytest.param(lambda s: s.delete_file_with_sidecar("/Photos", "img.jpg"), id="delete_with_sidecar"),
    ],
)
async def test_every_write_path_invalidates_the_cached_thumbnail(counting_storage, write) -> None:
    """Curation, publish-archive and delete share the storage instance that serves thumbnails."""
    storage, client = counting_storage
    await _cached_thumb(storage)
    gets = client.get_calls

    await write(storage)
    client.body = _png("blue")
    client.etag = '"etag-2"'
    regenerated = await _cached_thumb(storage)

    assert client.get_calls == gets + 1
    assert regenerated is not None


async def test_a_write_during_a_thumbnail_download_is_never_cached(counting_storage) -> None:
    """#140: bytes read before an invalidation must not land in the cache afterwards."""
    storage, client = counting_storage
    original_download = storage.download_image

    async def _download_then_write(folder: str, filename: str) -> bytes:
        data = await original_download(folder, filename)
        storage.invalidate_thumbnail("Photos/img.jpg")  # an upload lands mid-flight
        return data

    storage.download_image = _download_then_write  # type: ignore[method-assign]
    await _cached_thumb(storage)
    storage.download_image = original_download  # type: ignore[method-assign]
    gets = client.get_calls

    await _cached_thumb(storage)

    assert client.get_calls == gets + 1  # nothing stale was cached
