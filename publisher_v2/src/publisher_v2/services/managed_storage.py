"""ManagedStorage — S3-compatible storage adapter implementing StorageProtocol.

Targets Cloudflare R2 but works with any S3-compatible backend (AWS S3, MinIO).
All boto3 calls are wrapped in asyncio.to_thread for non-blocking execution.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any, cast

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.exceptions import ConnectionError as BotoConnectionError
from PIL import Image
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from publisher_v2.config.runtime_settings import RuntimeSettings, load_runtime_settings
from publisher_v2.config.schema import ManagedStorageConfig
from publisher_v2.core.exceptions import StorageError
from publisher_v2.services.storage_protocol import FileMetadata, ThumbnailFormat, ThumbnailSize
from publisher_v2.utils.logging import log_json
from publisher_v2.utils.memory_io import reader_over

logger = logging.getLogger("publisher_v2.services.managed_storage")

# Beyond this many keys the generation counter is pruned of entries that no
# longer guard a cached thumbnail (#140).
_THUMB_GENERATION_MAX_KEYS = 4096
# Same for the single-flight lock map and the recorded-ETag map.
_THUMB_LOCK_MAX_KEYS = 4096
_LAST_GET_ETAG_MAX_KEYS = 256

# Map protocol ThumbnailSize values to (width, height) for Pillow resize
_SIZE_MAP: dict[str, tuple[int, int]] = {
    "w256h256": (256, 256),
    "w480h320": (480, 320),
    "w640h480": (640, 480),
    "w960h640": (960, 640),
    "w1024h768": (1024, 768),
}

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def _is_transient_s3_error(exc: BaseException) -> bool:
    """Return True for transient S3 errors that should be retried."""
    if isinstance(exc, BotoConnectionError | EndpointConnectionError):
        return True
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        # Retry on 5xx and throttling
        if status >= 500 or code in ("SlowDown", "ServiceUnavailable", "InternalError"):
            return True
    return False


# #140: (endpoint, bucket, key, size) → (thumbnail bytes, stored_at, etag)
_ThumbKey = tuple[str, str, str, str]
_ThumbEntry = tuple[bytes, float, str]


class ManagedStorage:
    """S3-compatible storage backend implementing StorageProtocol."""

    def __init__(self, config: ManagedStorageConfig, settings: RuntimeSettings | None = None) -> None:
        self.config = config
        # #143: thumbnail cache tunables are read once here, not per request.
        self._settings = settings if settings is not None else load_runtime_settings()
        boto_config = BotoConfig(
            connect_timeout=30,
            read_timeout=60,
            # #93: tenacity is the single retry layer (mirrors #84/#88).
            retries={"max_attempts": 1, "mode": "standard"},
        )
        self.client: Any = boto3.client(
            "s3",
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            endpoint_url=config.endpoint_url,
            region_name=config.region,
            config=boto_config,
        )
        self._bucket = config.bucket
        # PUB-045: R2 storage operation counter (drained by StorageOpsMeter)
        self._ops_count: int = 0
        self._ops_lock = threading.Lock()
        # #86: per-instance thumbnail cache with a TTL and a byte budget — a
        # module-global cache let tenants with the same key path see each other's
        # thumbnails and served stale entries after re-uploads.
        # #140: keyed by (endpoint, bucket, key, size) — NOT by ETag, so a cache
        # hit needs no head_object. The ETag rides along in the entry and is only
        # re-checked once the entry is older than the TTL.
        self._thumb_cache: OrderedDict[_ThumbKey, _ThumbEntry] = OrderedDict()
        # #140: bumped on every write to a key; a thumbnail read that started
        # before the bump is dropped instead of cached.
        self._thumb_generation: OrderedDict[str, int] = OrderedDict()
        # Key -> the ETag its last GET returned; popped by the thumbnail cache.
        # Bounded: every download in the process writes here (workflow, analyze,
        # the migration tool), while only a thumbnail regeneration reads.
        self._last_get_etags: OrderedDict[str, str] = OrderedDict()
        # Per-key single-flight locks, with the loop each was created on.
        self._thumb_locks: OrderedDict[_ThumbKey, tuple[asyncio.AbstractEventLoop, asyncio.Lock]] = OrderedDict()
        self._thumb_cache_bytes = 0

    def _count_ops(self, n: int = 1) -> None:
        """Increment the R2 operation counter (thread-safe). PUB-045."""
        with self._ops_lock:
            self._ops_count += n

    def drain_ops_count(self) -> int:
        """Atomically read and reset the operation counter. PUB-045."""
        with self._ops_lock:
            count = self._ops_count
            self._ops_count = 0
            return count

    def _key(self, folder: str, filename: str) -> str:
        """Build an S3 object key from folder + filename."""
        return f"{folder.strip('/')}/{filename}".lstrip("/")

    def _sidecar_key(self, folder: str, filename: str) -> str:
        """Build the .txt sidecar key for an image."""
        stem = os.path.splitext(filename)[0]
        return self._key(folder, f"{stem}.txt")

    @staticmethod
    def _move_destination_prefix(folder: str, target_subfolder: str) -> str:
        """Resolve destination key prefix for curation moves.

        ``target_subfolder`` is either a single segment (``keep``) or an absolute
        key prefix under the bucket (``tenant/root/keep`` from orchestrator).
        """
        fn = folder.strip("/")
        ts = target_subfolder.strip("/")
        if not ts:
            return fn
        if ts.startswith(fn + "/") or ts == fn:
            return ts
        return f"{fn}/{ts}"

    @staticmethod
    def _is_immediate_child_object_key(folder: str, key: str) -> bool:
        """True if key is a direct object under folder (not in a nested sub-prefix).

        Matches Dropbox ``list_folder`` semantics: only files in the given folder,
        excluding keys like ``{folder}/archive/photo.jpg`` whose basename would
        collide with ``{folder}/photo.jpg`` in a flat filename list.
        """
        prefix = f"{folder.strip('/')}/"
        if not key.startswith(prefix):
            return False
        relative = key[len(prefix) :]
        if not relative or relative.endswith("/"):
            return False
        return "/" not in relative

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_transient_s3_error),
    )
    async def list_images(self, folder: str) -> list[str]:
        try:

            def _list() -> list[str]:
                prefix = f"{folder.strip('/')}/"
                names: list[str] = []
                paginator = self.client.get_paginator("list_objects_v2")
                for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                    self._count_ops()  # PUB-045: count each page as one R2 request
                    for obj in page.get("Contents", []):
                        key: str = obj["Key"]
                        if not ManagedStorage._is_immediate_child_object_key(folder, key):
                            continue
                        fname = key.rsplit("/", 1)[-1]
                        if fname.lower().endswith(_IMAGE_EXTENSIONS):
                            names.append(fname)
                return names

            return await asyncio.to_thread(_list)
        except ClientError as exc:
            raise StorageError(f"Failed to list images: {exc}") from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_transient_s3_error),
    )
    async def list_images_with_hashes(self, folder: str) -> list[tuple[str, str]]:
        try:

            def _list() -> list[tuple[str, str]]:
                prefix = f"{folder.strip('/')}/"
                out: list[tuple[str, str]] = []
                paginator = self.client.get_paginator("list_objects_v2")
                for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                    self._count_ops()  # PUB-045: count each page as one R2 request
                    for obj in page.get("Contents", []):
                        key: str = obj["Key"]
                        if not ManagedStorage._is_immediate_child_object_key(folder, key):
                            continue
                        fname = key.rsplit("/", 1)[-1]
                        if fname.lower().endswith(_IMAGE_EXTENSIONS):
                            etag = (obj.get("ETag") or "").strip('"')
                            out.append((fname, etag))
                return out

            return await asyncio.to_thread(_list)
        except ClientError as exc:
            raise StorageError(f"Failed to list images with hashes: {exc}") from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_transient_s3_error),
    )
    async def download_image(self, folder: str, filename: str) -> bytes:
        key = self._key(folder, filename)
        try:

            def _download() -> bytes:
                self._count_ops()  # PUB-045: one count per get_object call (boto's internal retries are NOT counted)
                resp = self.client.get_object(Bucket=self._bucket, Key=key)
                expected_length = resp.get("ContentLength")
                body = resp["Body"].read()
                actual_length = len(body)
                if expected_length is not None and actual_length != expected_length:
                    raise StorageError(
                        f"Incomplete download for {filename}: expected {expected_length} bytes, got {actual_length}"
                    )
                # #140: the GET response carries the ETag. Recording it here lets
                # the thumbnail cache label an entry whose HEAD failed, instead of
                # storing it unlabelled and re-downloading at every expiry for the
                # rest of its life. No extra request.
                self._last_get_etags[key] = (resp.get("ETag") or "").strip('"')
                self._last_get_etags.move_to_end(key)
                while len(self._last_get_etags) > _LAST_GET_ETAG_MAX_KEYS:
                    self._last_get_etags.popitem(last=False)
                return cast(bytes, body)

            return await asyncio.to_thread(_download)
        except ClientError as exc:
            raise StorageError(f"Failed to download {filename}: {exc}") from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_transient_s3_error),
    )
    async def get_temporary_link(self, folder: str, filename: str) -> str:
        try:

            def _link() -> str:
                key = self._key(folder, filename)
                return cast(
                    str,
                    self.client.generate_presigned_url(
                        "get_object",
                        Params={"Bucket": self._bucket, "Key": key},
                        ExpiresIn=3600,
                    ),
                )

            return await asyncio.to_thread(_link)
        except ClientError as exc:
            raise StorageError(f"Failed to get temporary link for {filename}: {exc}") from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_transient_s3_error),
    )
    async def get_file_metadata(self, folder: str, filename: str) -> FileMetadata:
        """Return normalized file identity/version metadata (#96)."""
        try:

            def _meta() -> FileMetadata:
                key = self._key(folder, filename)
                self._count_ops()  # PUB-045: count head_object
                resp = self.client.head_object(Bucket=self._bucket, Key=key)
                etag = (resp.get("ETag") or "").strip('"') or None
                modified = str(resp.get("LastModified") or "") or None
                size = resp.get("ContentLength")
                return FileMetadata(file_id=key, revision=etag, modified_at=modified, size=size)

            return await asyncio.to_thread(_meta)
        except ClientError as exc:
            raise StorageError(f"Failed to get metadata for {filename}: {exc}") from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_transient_s3_error),
    )
    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        try:

            def _upload() -> None:
                key = self._sidecar_key(folder, filename)
                self._count_ops()  # PUB-045: count put_object
                self.client.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=text.encode("utf-8"),
                    ContentType="text/plain; charset=utf-8",
                )

            await asyncio.to_thread(_upload)
        except ClientError as exc:
            raise StorageError(f"Failed to upload sidecar for {filename}: {exc}") from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_transient_s3_error),
    )
    async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None:
        try:

            def _download() -> bytes | None:
                key = self._sidecar_key(folder, filename)
                self._count_ops()  # PUB-045: count request even on 404 (R2 bills it)
                try:
                    resp = self.client.get_object(Bucket=self._bucket, Key=key)
                    return cast(bytes, resp["Body"].read())
                except ClientError as inner_exc:
                    code = inner_exc.response.get("Error", {}).get("Code", "")
                    if code in ("NoSuchKey", "404"):
                        return None
                    raise

            return await asyncio.to_thread(_download)
        except ClientError as exc:
            raise StorageError(f"Failed to download sidecar for {filename}: {exc}") from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_transient_s3_error),
    )
    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        try:

            def _archive() -> None:
                src_key = self._key(folder, filename)
                dst_key = self._key(archive_folder, filename)
                copy_src = {"Bucket": self._bucket, "Key": src_key}
                self._count_ops()  # PUB-045: image copy
                self.client.copy_object(Bucket=self._bucket, Key=dst_key, CopySource=copy_src)
                self._count_ops()  # PUB-045: image delete
                self.client.delete_object(Bucket=self._bucket, Key=src_key)
                # Move sidecar if exists
                sidecar_src = self._sidecar_key(folder, filename)
                sidecar_dst = self._sidecar_key(archive_folder, filename)
                try:
                    self._count_ops()  # PUB-045: sidecar copy attempt (R2 bills it even on failure)
                    self.client.copy_object(
                        Bucket=self._bucket, Key=sidecar_dst, CopySource={"Bucket": self._bucket, "Key": sidecar_src}
                    )
                    self._count_ops()  # PUB-045: sidecar delete
                    self.client.delete_object(Bucket=self._bucket, Key=sidecar_src)
                except ClientError:
                    pass  # Sidecar may not exist

            await asyncio.to_thread(_archive)
        except ClientError as exc:
            raise StorageError(f"Failed to archive {filename}: {exc}") from exc
        finally:
            # #140: also on failure. A partly applied write (copy done, delete
            # raised) otherwise leaves a stale thumbnail on the destination key.
            self.invalidate_thumbnail(self._key(folder, filename), self._key(archive_folder, filename))

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_transient_s3_error),
    )
    async def move_image_with_sidecars(self, folder: str, filename: str, target_subfolder: str) -> None:
        try:

            def _move() -> None:
                src_key = self._key(folder, filename)
                dest_prefix = ManagedStorage._move_destination_prefix(folder, target_subfolder)
                dst_key = self._key(dest_prefix, filename)
                copy_src = {"Bucket": self._bucket, "Key": src_key}
                self._count_ops()  # PUB-045: image copy
                self.client.copy_object(Bucket=self._bucket, Key=dst_key, CopySource=copy_src)
                self._count_ops()  # PUB-045: image delete
                self.client.delete_object(Bucket=self._bucket, Key=src_key)
                # Move sidecar
                sidecar_src = self._sidecar_key(folder, filename)
                stem = os.path.splitext(filename)[0]
                sidecar_dst = self._key(dest_prefix, f"{stem}.txt")
                try:
                    self._count_ops()  # PUB-045: sidecar copy attempt
                    self.client.copy_object(
                        Bucket=self._bucket, Key=sidecar_dst, CopySource={"Bucket": self._bucket, "Key": sidecar_src}
                    )
                    self._count_ops()  # PUB-045: sidecar delete
                    self.client.delete_object(Bucket=self._bucket, Key=sidecar_src)
                except ClientError:
                    pass  # Sidecar may not exist

            await asyncio.to_thread(_move)
        except ClientError as exc:
            raise StorageError(f"Failed to move {filename} to {target_subfolder}: {exc}") from exc
        finally:
            dest_prefix = ManagedStorage._move_destination_prefix(folder, target_subfolder)
            self.invalidate_thumbnail(self._key(folder, filename), self._key(dest_prefix, filename))

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_transient_s3_error),
    )
    async def delete_file_with_sidecar(self, folder: str, filename: str) -> None:
        try:

            def _delete() -> None:
                key = self._key(folder, filename)
                self._count_ops()  # PUB-045: image delete
                self.client.delete_object(Bucket=self._bucket, Key=key)
                sidecar = self._sidecar_key(folder, filename)
                with contextlib.suppress(ClientError):
                    self._count_ops()  # PUB-045: sidecar delete attempt
                    self.client.delete_object(Bucket=self._bucket, Key=sidecar)

            await asyncio.to_thread(_delete)
        except ClientError as exc:
            raise StorageError(f"Failed to delete {filename}: {exc}") from exc
        finally:
            self.invalidate_thumbnail(self._key(folder, filename))

    async def ensure_folder_exists(self, folder_path: str) -> None:
        """No-op — S3 has no real folders."""
        return

    # ------------------------------------------------------------------
    # Object-level operations (#96): the admin library router calls ONLY
    # these — no more reaching into ._bucket/.client from the web layer.
    # PUB-045 metering stays inside each method.
    # ------------------------------------------------------------------

    async def list_objects(self, prefix: str, cursor: str | None = None, limit: int = 1000) -> dict[str, Any]:
        """One listing page (Delimiter='/'): immediate children only."""

        def _list() -> dict[str, Any]:
            kwargs: dict[str, Any] = {
                "Bucket": self._bucket,
                "Prefix": prefix,
                "Delimiter": "/",
                "MaxKeys": min(1000, max(1, limit)),
            }
            if cursor:
                kwargs["ContinuationToken"] = cursor
            self._count_ops()  # PUB-045: each list page is a billable request
            resp = self.client.list_objects_v2(**kwargs)
            items = [
                {
                    "key": obj["Key"],
                    "size": obj.get("Size", 0),
                    "last_modified": obj.get("LastModified"),
                }
                for obj in resp.get("Contents", [])
            ]
            return {
                "items": items,
                "cursor": resp.get("NextContinuationToken") if resp.get("IsTruncated") else None,
                "is_truncated": bool(resp.get("IsTruncated")),
            }

        try:
            return await asyncio.to_thread(_list)
        except ClientError as exc:
            raise StorageError(f"Failed to list objects under {prefix}: {exc}") from exc

    async def put_object(self, key: str, data: bytes | bytearray | memoryview, content_type: str) -> None:
        def _put() -> None:
            self._count_ops()
            # #136: botocore copies a bytearray Body (io.BytesIO for checksums);
            # hand it a zero-copy file instead. It must stay seekable: botocore
            # rewinds the body with seek(0) before each retry attempt.
            if isinstance(data, bytes):
                self.client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
                return
            reader = reader_over(data)
            try:
                self.client.put_object(Bucket=self._bucket, Key=key, Body=reader, ContentType=content_type)
            finally:
                # Release the memoryview rather than leaving the caller's buffer
                # un-resizable until the reader is collected.
                reader.close()

        try:
            await asyncio.to_thread(_put)
        except ClientError as exc:
            raise StorageError(f"Failed to put object {key}: {exc}") from exc
        finally:
            self.invalidate_thumbnail(key)

    async def head_object(self, key: str) -> dict[str, Any] | None:
        def _head() -> dict[str, Any] | None:
            self._count_ops()
            try:
                resp = self.client.head_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                # #142: presence is now the migration tool's only resume gate, so a
                # 403 or a throttle read as "missing" would silently re-copy the
                # whole library. Absence is expected and stays quiet; anything else
                # is a fault worth a line.
                code = str((exc.response or {}).get("Error", {}).get("Code", ""))
                if code not in ("404", "NoSuchKey", "NotFound"):
                    log_json(
                        logger,
                        logging.WARNING,
                        "head_object_failed",
                        code=code or "unknown",
                        key_length=len(key),
                    )
                return None
            return {
                "size": resp.get("ContentLength"),
                "etag": (resp.get("ETag") or "").strip('"') or None,
                "last_modified": resp.get("LastModified"),
            }

        return await asyncio.to_thread(_head)

    async def exists(self, key: str) -> bool:
        """True when the object is present (#142). One head_object, counted."""
        return await self.head_object(key) is not None

    async def delete_object(self, key: str) -> None:
        def _delete() -> None:
            self._count_ops()
            self.client.delete_object(Bucket=self._bucket, Key=key)

        try:
            await asyncio.to_thread(_delete)
        except ClientError as exc:
            raise StorageError(f"Failed to delete object {key}: {exc}") from exc
        finally:
            self.invalidate_thumbnail(key)

    async def move_object(self, src_key: str, dst_key: str) -> None:
        def _move() -> None:
            self._count_ops(2)  # copy + delete
            self.client.copy_object(
                Bucket=self._bucket, Key=dst_key, CopySource={"Bucket": self._bucket, "Key": src_key}
            )
            self.client.delete_object(Bucket=self._bucket, Key=src_key)

        try:
            await asyncio.to_thread(_move)
        except ClientError as exc:
            raise StorageError(f"Failed to move {src_key} -> {dst_key}: {exc}") from exc
        finally:
            self.invalidate_thumbnail(src_key, dst_key)

    def supports_content_hashing(self) -> bool:
        """ETag-based content hashing is supported."""
        return True

    async def get_thumbnail(
        self,
        folder: str,
        filename: str,
        size: ThumbnailSize = ThumbnailSize.W960H640,
        format: ThumbnailFormat = ThumbnailFormat.JPEG,
    ) -> bytes:
        """Generate thumbnail via Pillow with a tenant-safe, TTL-bounded cache (#86, #140)."""
        key = self._key(folder, filename)
        cache_key = (self.config.endpoint_url, self._bucket, key, str(size))

        # #140: N concurrent misses on one key would each pay HEAD + GET + Pillow.
        # The first caller through does the work; the rest wait and then find the
        # entry in the cache.
        async with self._thumb_lock(cache_key):
            return await self._get_thumbnail_locked(folder, filename, cache_key, size, format)

    def _thumb_lock(self, cache_key: _ThumbKey) -> asyncio.Lock:
        """One lock per cache key, rebuilt if the running loop changed.

        A service instance outlives the loop that created it in tests (and after
        a restarted loop in production), and awaiting a lock bound to a dead loop
        raises rather than blocking.
        """
        loop = asyncio.get_running_loop()
        existing = self._thumb_locks.get(cache_key)
        if existing is None or existing[0] is not loop:
            existing = (loop, asyncio.Lock())
        self._thumb_locks[cache_key] = existing
        self._thumb_locks.move_to_end(cache_key)
        # Evicting a held lock would let the next arrival build a fresh one and
        # lose mutual exclusion, so skip anything currently locked; the map also
        # keeps a loop alive, which is the other reason to keep it small.
        for key in [k for k in self._thumb_locks if len(self._thumb_locks) > _THUMB_LOCK_MAX_KEYS]:
            if key == cache_key or self._thumb_locks[key][1].locked():
                continue
            del self._thumb_locks[key]
        return existing[1]

    async def _get_thumbnail_locked(
        self,
        folder: str,
        filename: str,
        cache_key: _ThumbKey,
        size: ThumbnailSize,
        format: ThumbnailFormat,
    ) -> bytes:
        now = time.time()
        entry = self._thumb_cache.get(cache_key)
        if entry is not None:
            data, stored_at, etag = entry
            if now - stored_at <= self._settings.thumbnail_cache_ttl_seconds:
                # #140: a fresh entry costs nothing — no head_object, no download.
                self._thumb_cache.move_to_end(cache_key)
                return data
            current_etag = ""
            with contextlib.suppress(Exception):
                meta = await self.get_file_metadata(folder, filename)
                current_etag = meta.revision or ""
            if current_etag and current_etag == etag:
                # Object unchanged: renew the entry instead of downloading again.
                self._thumb_cache[cache_key] = (data, now, etag)
                self._thumb_cache.move_to_end(cache_key)
                return data
            self._evict_thumb(cache_key)
            # The HEAD above already produced the new ETag — don't pay for it twice.
            return await self._regenerate_thumbnail(folder, filename, cache_key, size, format, now, current_etag)

        etag = ""
        with contextlib.suppress(Exception):
            meta = await self.get_file_metadata(folder, filename)
            etag = meta.revision or ""
        return await self._regenerate_thumbnail(folder, filename, cache_key, size, format, now, etag)

    async def _regenerate_thumbnail(
        self,
        folder: str,
        filename: str,
        cache_key: _ThumbKey,
        size: ThumbnailSize,
        format: ThumbnailFormat,
        now: float,
        etag: str,
    ) -> bytes:
        """Download and render one thumbnail, caching it unless the object changed meanwhile."""
        generation = self._thumb_generation.get(cache_key[2], 0)
        image_bytes = await self.download_image(folder, filename)
        # #140: a HEAD that failed leaves etag empty, and an entry stored without
        # one can never be revalidated. The GET above already carried the ETag,
        # so take it from there rather than buying a second HEAD.
        recorded = self._last_get_etags.pop(cache_key[2], "")
        etag = etag or recorded
        thumb_bytes = await asyncio.to_thread(_generate_thumbnail, image_bytes, str(size), str(format))
        # #140: cache only when no write landed on this key while we were
        # downloading — otherwise these bytes are already stale, so they go to
        # this caller and nowhere else.
        if self._thumb_generation.get(cache_key[2], 0) == generation:
            self._store_thumb(cache_key, thumb_bytes, now, etag)
        return thumb_bytes

    def invalidate_thumbnail(self, *keys: str) -> None:
        """Drop every cached thumbnail for these object keys (#140).

        Called by this class's own write methods, so every caller — library
        router, curation, publish-archive — is covered. The generation counter
        also discards a thumbnail whose download started before the write, which
        would otherwise be stored after the eviction and served for a full TTL.
        """
        for key in keys:
            normalized = key.strip("/")
            self._thumb_generation[normalized] = self._thumb_generation.get(normalized, 0) + 1
            self._thumb_generation.move_to_end(normalized)
            for cache_key in [k for k in self._thumb_cache if k[2] == normalized]:
                self._evict_thumb(cache_key)
        # The counter gained an entry per distinct key ever written and was only
        # cleared in aclose(), so a long-lived tenant service grew it without
        # bound. Drop the oldest entries that no longer guard a cached thumbnail;
        # a key with no cache entry has nothing to invalidate a download against.
        if len(self._thumb_generation) > _THUMB_GENERATION_MAX_KEYS:
            cached = {k[2] for k in self._thumb_cache}
            for key in [k for k in self._thumb_generation if k not in cached]:
                if len(self._thumb_generation) <= _THUMB_GENERATION_MAX_KEYS:
                    break
                del self._thumb_generation[key]

    def _evict_thumb(self, cache_key: _ThumbKey) -> None:
        entry = self._thumb_cache.pop(cache_key, None)
        if entry is not None:
            self._thumb_cache_bytes -= len(entry[0])

    def _store_thumb(self, cache_key: _ThumbKey, data: bytes, now: float, etag: str) -> None:
        budget = self._settings.thumbnail_cache_max_bytes
        if len(data) > budget:
            return
        while self._thumb_cache and self._thumb_cache_bytes + len(data) > budget:
            oldest_key = next(iter(self._thumb_cache))
            self._evict_thumb(oldest_key)
        self._thumb_cache[cache_key] = (data, now, etag)
        self._thumb_cache_bytes += len(data)

    async def aclose(self) -> None:
        """Close the underlying boto3 client and drop the thumbnail cache (#86)."""
        self._thumb_cache.clear()
        self._thumb_cache_bytes = 0
        self._thumb_generation.clear()
        self._thumb_locks.clear()
        self._last_get_etags.clear()
        with contextlib.suppress(Exception):
            await asyncio.to_thread(self.client.close)


def _generate_thumbnail(image_bytes: bytes, size_str: str, fmt_str: str) -> bytes:
    """CPU-bound thumbnail generation with Pillow."""
    dims = _SIZE_MAP.get(size_str, (960, 640))
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail(dims, Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    output_format = "PNG" if fmt_str == "png" else "JPEG"
    img.save(buf, format=output_format)
    return buf.getvalue()
