"""ManagedStorage — S3-compatible storage adapter implementing StorageProtocol.

Targets Cloudflare R2 but works with any S3-compatible backend (AWS S3, MinIO).
All boto3 calls are wrapped in asyncio.to_thread for non-blocking execution.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
from typing import Any, cast

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.exceptions import ConnectionError as BotoConnectionError
from PIL import Image
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from publisher_v2.config.schema import ManagedStorageConfig
from publisher_v2.core.exceptions import StorageError
from publisher_v2.services.storage_protocol import ThumbnailFormat, ThumbnailSize

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
    if isinstance(exc, (BotoConnectionError, EndpointConnectionError)):
        return True
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        # Retry on 5xx and throttling
        if status >= 500 or code in ("SlowDown", "ServiceUnavailable", "InternalError"):
            return True
    return False


class ManagedStorage:
    """S3-compatible storage backend implementing StorageProtocol."""

    def __init__(self, config: ManagedStorageConfig) -> None:
        self.config = config
        self.client: Any = boto3.client(
            "s3",
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            endpoint_url=config.endpoint_url,
            region_name=config.region,
        )
        self._bucket = config.bucket

    def _key(self, folder: str, filename: str) -> str:
        """Build an S3 object key from folder + filename."""
        return f"{folder.strip('/')}/{filename}".lstrip("/")

    def _sidecar_key(self, folder: str, filename: str) -> str:
        """Build the .txt sidecar key for an image."""
        stem = os.path.splitext(filename)[0]
        return self._key(folder, f"{stem}.txt")

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
        try:

            def _download() -> bytes:
                key = self._key(folder, filename)
                resp = self.client.get_object(Bucket=self._bucket, Key=key)
                return cast(bytes, resp["Body"].read())

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
    async def get_file_metadata(self, folder: str, filename: str) -> dict[str, str]:
        try:

            def _meta() -> dict[str, str]:
                key = self._key(folder, filename)
                resp = self.client.head_object(Bucket=self._bucket, Key=key)
                out: dict[str, str] = {}
                if resp.get("ETag"):
                    out["ETag"] = resp["ETag"].strip('"')
                if resp.get("LastModified"):
                    out["LastModified"] = str(resp["LastModified"])
                return out

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
                self.client.copy_object(Bucket=self._bucket, Key=dst_key, CopySource=copy_src)
                self.client.delete_object(Bucket=self._bucket, Key=src_key)
                # Move sidecar if exists
                sidecar_src = self._sidecar_key(folder, filename)
                sidecar_dst = self._sidecar_key(archive_folder, filename)
                try:
                    self.client.copy_object(
                        Bucket=self._bucket, Key=sidecar_dst, CopySource={"Bucket": self._bucket, "Key": sidecar_src}
                    )
                    self.client.delete_object(Bucket=self._bucket, Key=sidecar_src)
                except ClientError:
                    pass  # Sidecar may not exist

            await asyncio.to_thread(_archive)
        except ClientError as exc:
            raise StorageError(f"Failed to archive {filename}: {exc}") from exc

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
                dst_key = self._key(f"{folder.strip('/')}/{target_subfolder}", filename)
                copy_src = {"Bucket": self._bucket, "Key": src_key}
                self.client.copy_object(Bucket=self._bucket, Key=dst_key, CopySource=copy_src)
                self.client.delete_object(Bucket=self._bucket, Key=src_key)
                # Move sidecar
                sidecar_src = self._sidecar_key(folder, filename)
                stem = os.path.splitext(filename)[0]
                sidecar_dst = self._key(f"{folder.strip('/')}/{target_subfolder}", f"{stem}.txt")
                try:
                    self.client.copy_object(
                        Bucket=self._bucket, Key=sidecar_dst, CopySource={"Bucket": self._bucket, "Key": sidecar_src}
                    )
                    self.client.delete_object(Bucket=self._bucket, Key=sidecar_src)
                except ClientError:
                    pass  # Sidecar may not exist

            await asyncio.to_thread(_move)
        except ClientError as exc:
            raise StorageError(f"Failed to move {filename} to {target_subfolder}: {exc}") from exc

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
                self.client.delete_object(Bucket=self._bucket, Key=key)
                sidecar = self._sidecar_key(folder, filename)
                with contextlib.suppress(ClientError):
                    self.client.delete_object(Bucket=self._bucket, Key=sidecar)

            await asyncio.to_thread(_delete)
        except ClientError as exc:
            raise StorageError(f"Failed to delete {filename}: {exc}") from exc

    async def ensure_folder_exists(self, folder_path: str) -> None:
        """No-op — S3 has no real folders."""
        return

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
        """Generate thumbnail via Pillow with LRU caching."""
        key = self._key(folder, filename)
        size_str = str(size)
        cached = _get_cached_thumbnail(key, size_str)
        if cached is not None:
            return cached

        image_bytes = await self.download_image(folder, filename)
        thumb_bytes = await asyncio.to_thread(_generate_thumbnail, image_bytes, size_str, str(format))
        _put_cached_thumbnail(key, size_str, thumb_bytes)
        return thumb_bytes


# ---------------------------------------------------------------------------
# Thumbnail cache (module-level LRU, keyed by (object_key, size))
# ---------------------------------------------------------------------------
_thumbnail_cache: dict[tuple[str, str], bytes] = {}
_CACHE_MAX = 500


def _get_cached_thumbnail(key: str, size: str) -> bytes | None:
    return _thumbnail_cache.get((key, size))


def _put_cached_thumbnail(key: str, size: str, data: bytes) -> None:
    if len(_thumbnail_cache) >= _CACHE_MAX:
        # Evict oldest entry (FIFO approximation)
        oldest = next(iter(_thumbnail_cache))
        del _thumbnail_cache[oldest]
    _thumbnail_cache[(key, size)] = data


def _generate_thumbnail(image_bytes: bytes, size_str: str, fmt_str: str) -> bytes:
    """CPU-bound thumbnail generation with Pillow."""
    dims = _SIZE_MAP.get(size_str, (960, 640))
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail(dims, Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    output_format = "PNG" if fmt_str == "png" else "JPEG"
    img.save(buf, format=output_format)
    return buf.getvalue()
