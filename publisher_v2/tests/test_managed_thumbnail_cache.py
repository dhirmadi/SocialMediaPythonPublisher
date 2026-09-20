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
def counting_storage(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Build the storage with the TTL already in the environment.

    Setting WEB_THUMBNAIL_CACHE_TTL_SECONDS after construction works only while
    the TTL is read per call; #143/#162 moves it to a RuntimeSettings snapshot
    taken in __init__, at which point a later setenv would silently stop
    controlling anything and these tests would pass for the wrong reason.
    """
    from unittest.mock import MagicMock, patch

    def _build(ttl: str | None = None) -> tuple[ManagedStorage, _CountingS3]:
        if ttl is not None:
            monkeypatch.setenv("WEB_THUMBNAIL_CACHE_TTL_SECONDS", ttl)
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

    return _build


async def test_cache_hit_within_ttl_issues_no_storage_ops(counting_storage) -> None:
    """#140 AC: the second thumbnail request inside the TTL must bill nothing."""
    storage, client = counting_storage("900")
    await storage.get_thumbnail("/Photos", "img.jpg")
    ops_after_first = (client.head_calls, client.get_calls)

    await storage.get_thumbnail("/Photos", "img.jpg")

    assert (client.head_calls, client.get_calls) == ops_after_first


async def test_expired_entry_revalidates_with_one_head_and_no_download(counting_storage) -> None:
    """Past the TTL the ETag is re-checked; an unchanged object must not be downloaded again."""
    storage, client = counting_storage("0")
    first = await storage.get_thumbnail("/Photos", "img.jpg")
    heads, gets = client.head_calls, client.get_calls

    second = await storage.get_thumbnail("/Photos", "img.jpg")

    assert second == first
    assert client.head_calls == heads + 1
    assert client.get_calls == gets


async def test_invalidated_key_regenerates_on_the_next_request(counting_storage) -> None:
    """An upload/move through the library invalidates the entry directly (#140)."""
    storage, client = counting_storage("900")
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
    storage, client = counting_storage("900")
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
    storage, client = counting_storage("900")
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


class TestConcurrentMissesShareOneDownload:
    """#140: N simultaneous misses on one key each paid HEAD + GET + Pillow."""

    async def test_ten_concurrent_misses_download_once(self) -> None:
        import asyncio

        storage = _storage("bucket-sf", _png("blue"))

        async def _slow_download(*_args, **_kwargs) -> bytes:
            await asyncio.sleep(0.05)
            return _png("blue")

        storage.download_image = AsyncMock(side_effect=_slow_download)  # type: ignore[method-assign]

        results = await asyncio.gather(*(storage.get_thumbnail("f", "a.png") for _ in range(10)))

        assert len({bytes(r) for r in results}) == 1
        assert storage.download_image.await_count == 1, "each waiter re-downloaded"
        assert storage.get_file_metadata.await_count == 1  # type: ignore[union-attr]

    async def test_two_different_keys_do_not_serialise_on_each_other(self) -> None:
        """The lock is per key: a slow render of one image must not block another."""
        import asyncio

        storage = _storage("bucket-sf2", _png("blue"))
        # Note this kills a single global lock, not the absence of a lock — its
        # companion above does that. Both are needed; neither is redundant.
        in_flight, peak = {"n": 0}, {"n": 0}

        async def _download(_folder: str, filename: str) -> bytes:
            in_flight["n"] += 1
            peak["n"] = max(peak["n"], in_flight["n"])
            await asyncio.sleep(0.05)
            in_flight["n"] -= 1
            return _png("blue" if filename == "a.png" else "green")

        storage.download_image = AsyncMock(side_effect=_download)  # type: ignore[method-assign]

        await asyncio.gather(storage.get_thumbnail("f", "a.png"), storage.get_thumbnail("f", "b.png"))

        assert peak["n"] == 2, "different keys serialised behind one lock"


class TestTheGenerationCounterIsBounded:
    """#140: it gained an entry per distinct key ever written and was only cleared in aclose()."""

    async def test_keys_with_no_cached_thumbnail_are_pruned(self) -> None:
        from publisher_v2.services.managed_storage import _THUMB_GENERATION_MAX_KEYS

        storage = _storage("bucket-gen", _png("red"))
        # A write puts the key in the counter; the fetch then caches a thumbnail
        # for it, which is what makes the counter entry worth keeping.
        storage.invalidate_thumbnail("f/keep.png")
        await storage.get_thumbnail("f", "keep.png")

        for i in range(_THUMB_GENERATION_MAX_KEYS + 50):
            storage.invalidate_thumbnail(f"f/gone-{i}.png")

        assert len(storage._thumb_generation) <= _THUMB_GENERATION_MAX_KEYS
        # The key that still has a cached thumbnail must survive: its counter is
        # what discards a download that started before the write.
        assert "f/keep.png" in storage._thumb_generation


class TestAFailedHeadStillLabelsTheEntry:
    """#140 NIT: an entry stored without an ETag can never be revalidated."""

    async def test_the_real_download_records_the_unquoted_etag(self, counting_storage) -> None:
        """Through the real GET path: boto returns a quoted ETag, the entry must carry it unquoted.

        The other test in this class stubs ``download_image``, so it exercises
        only the consumer. This one covers the producer, including the strip
        that lets the stored value compare equal to ``FileMetadata.revision``.
        """
        from unittest.mock import AsyncMock

        storage, _client = counting_storage("900")
        storage.get_file_metadata = AsyncMock(side_effect=RuntimeError("HEAD blew up"))  # type: ignore[method-assign]

        await storage.get_thumbnail("/Photos", "img.jpg")

        cache_key = ("https://example.r2.local", "bucket-a", "Photos/img.jpg", "w960h640")
        _data, _stored_at, etag = storage._thumb_cache[cache_key]
        assert etag == "etag-1", "a quoted or missing ETag never matches the HEAD revision"
        assert storage._last_get_etags == {}, "the recorded entry must be drained, not accumulated"

    async def test_the_etag_comes_from_the_download_when_the_head_fails(self) -> None:
        storage = _storage("bucket-etag", _png("red"))
        storage.get_file_metadata = AsyncMock(side_effect=RuntimeError("HEAD blew up"))  # type: ignore[method-assign]

        # The real download path records the ETag its GET returned.
        async def _download(folder: str, filename: str) -> bytes:
            storage._last_get_etags[storage._key(folder, filename)] = "etag-from-get"
            return _png("red")

        storage.download_image = AsyncMock(side_effect=_download)  # type: ignore[method-assign]

        await storage.get_thumbnail("f", "a.png")

        cache_key = ("https://example.r2.local", "bucket-etag", "f/a.png", "w960h640")
        _data, _stored_at, etag = storage._thumb_cache[cache_key]
        assert etag == "etag-from-get", "an unlabelled entry re-downloads at every expiry, forever"


class TestAFailedWriteStillInvalidates:
    """#140: invalidation ran only on the success path.

    A partly applied write — the copy lands, the delete raises after tenacity
    gives up — left the destination key serving a stale thumbnail for a full TTL.
    """

    @staticmethod
    def _client_error():
        from botocore.exceptions import ClientError

        return ClientError({"Error": {"Code": "500", "Message": "boom"}}, "PutObject")

    async def test_a_put_that_raises_still_drops_the_cached_thumbnail(self) -> None:
        from unittest.mock import MagicMock

        storage = _storage("bucket-fail", _png("red"))
        await storage.get_thumbnail("f", "a.png")
        cache_key = ("https://example.r2.local", "bucket-fail", "f/a.png", "w960h640")
        assert cache_key in storage._thumb_cache

        storage.client = MagicMock()
        storage.client.put_object.side_effect = self._client_error()

        with pytest.raises(Exception, match="Failed to put object"):
            await storage.put_object("f/a.png", b"new-bytes", "image/png")

        assert cache_key not in storage._thumb_cache, "a failed write left a stale thumbnail cached"

    async def test_a_move_that_raises_still_drops_both_sides(self) -> None:
        from unittest.mock import MagicMock

        storage = _storage("bucket-fail2", _png("red"))
        await storage.get_thumbnail("f", "a.png")
        await storage.get_thumbnail("f", "b.png")
        src = ("https://example.r2.local", "bucket-fail2", "f/a.png", "w960h640")
        dst = ("https://example.r2.local", "bucket-fail2", "f/b.png", "w960h640")
        assert src in storage._thumb_cache and dst in storage._thumb_cache

        storage.client = MagicMock()
        # The copy lands, the delete raises: the destination now holds new bytes.
        storage.client.delete_object.side_effect = self._client_error()

        with pytest.raises(Exception, match="Failed to move"):
            await storage.move_object("f/a.png", "f/b.png")

        assert src not in storage._thumb_cache
        assert dst not in storage._thumb_cache, "the destination served the old image after a partial move"
