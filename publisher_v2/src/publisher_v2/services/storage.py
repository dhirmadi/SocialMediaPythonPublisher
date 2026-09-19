import asyncio
import contextlib
import os
from typing import cast

import dropbox
from dropbox.exceptions import (
    ApiError,
    AuthError,
    BadInputError,
    DropboxException,
    InternalServerError,
    RateLimitError,
)
from dropbox.files import (
    PathOrLink,
    ThumbnailMode,
)
from dropbox.files import (
    ThumbnailFormat as DbxThumbnailFormat,
)
from dropbox.files import (
    ThumbnailSize as DbxThumbnailSize,
)
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from publisher_v2.config.schema import DropboxConfig
from publisher_v2.core.exceptions import StorageAuthError, StorageError
from publisher_v2.services.storage_protocol import (
    FileMetadata,
    StorageNotSupportedError,
    ThumbnailFormat,
    ThumbnailSize,
)


def _is_retryable_dropbox_error(exc: BaseException) -> bool:
    """Predicate: retry on transient Dropbox API errors, never on permanent ones.

    #88: explicit classes — AuthError and BadInputError are permanent;
    RateLimitError and InternalServerError (5xx) are transient. Wrapped
    StorageError is judged by its __cause__. Dropbox path-shaped ApiErrors
    (not_found, conflict) stay permanent. Network failures retry.
    """
    if isinstance(exc, StorageError):
        cause = exc.__cause__
        if cause is None or cause is exc:
            return False
        return _is_retryable_dropbox_error(cause)
    if isinstance(exc, AuthError | BadInputError):
        return False
    if isinstance(exc, RateLimitError | InternalServerError):
        return True
    if isinstance(exc, ApiError):
        err = getattr(exc, "error", None)
        # Path-shaped errors (auth, not_found) are permanent — don't retry.
        return not (err is not None and hasattr(err, "is_path") and err.is_path())
    # Network and transport-level errors (best-effort detection without
    # importing requests/httpx eagerly).
    return type(exc).__name__ in {
        "ConnectionError",
        "ConnectTimeout",
        "ReadTimeout",
        "Timeout",
    }


_EXPONENTIAL_WAIT = wait_exponential(multiplier=1, min=1, max=8)


def _dropbox_wait(retry_state) -> float:  # type: ignore[no-untyped-def]
    """Honour RateLimitError.backoff when present, else exponential (#88)."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    cause = getattr(exc, "__cause__", None) or exc
    backoff = getattr(cause, "backoff", None)
    if backoff:
        return float(backoff)
    return float(_EXPONENTIAL_WAIT(retry_state))


# One retry layer (#88): the SDK's own retries are disabled below, so the
# bounded worst case per operation is 3 attempts x 30s timeout + waits — about
# two minutes, instead of 100s SDK timeout x 4 SDK retries x 3 tenacity tries.
_dropbox_retry = retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=lambda retry_state: _dropbox_wait(retry_state),
    retry=retry_if_exception(_is_retryable_dropbox_error),
)


def _wrap_dropbox_exception(exc: DropboxException, message: str) -> StorageError:
    """Map an SDK exception to the right StorageError subtype (#88)."""
    if isinstance(exc, AuthError):
        return StorageAuthError(f"dropbox auth failed: {message}")
    return StorageError(f"{message}: {exc}")


def _dropbox_move_destination_dir(folder: str, target_subfolder: str) -> str:
    """Destination directory for curation moves (relative segment or full Dropbox path)."""
    fn = folder.rstrip("/")
    ts = target_subfolder.strip()
    ts_n = ts.rstrip("/")
    if ts_n.startswith(fn + "/") or ts_n == fn:
        return ts
    return os.path.join(folder, target_subfolder)


class DropboxStorage:
    def __init__(self, config: DropboxConfig):
        self.config = config
        self.client = dropbox.Dropbox(
            oauth2_refresh_token=config.refresh_token,
            app_key=config.app_key,
            app_secret=config.app_secret,
            # #88: bounded HTTP timeout; tenacity is the single retry layer.
            timeout=30,
            max_retries_on_error=0,
        )

    @_dropbox_retry
    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        """
        Write or overwrite a .txt sidecar beside the image. For 'image.jpg' writes 'image.txt'.
        """
        try:

            def _upload() -> None:
                stem = os.path.splitext(filename)[0]
                sidecar_name = f"{stem}.txt"
                path = os.path.join(folder, sidecar_name)
                data = text.encode("utf-8")
                self.client.files_upload(
                    data,
                    path,
                    mode=dropbox.files.WriteMode.overwrite,
                    mute=True,
                )

            await asyncio.to_thread(_upload)
        except DropboxException as exc:
            raise _wrap_dropbox_exception(exc, f"Failed to upload sidecar for {filename}") from exc

    @staticmethod
    def _is_sidecar_not_found_error(exc: ApiError) -> bool:
        """
        Return True when the given ApiError represents a "file not found" condition
        for a path-based operation (e.g., sidecar download).
        """

        error = getattr(exc, "error", None)
        if error is None:
            return False
        # Dropbox SDK models path errors with is_path()/get_path(), and the
        # nested object exposes is_not_found() when the file is missing.
        if hasattr(error, "is_path") and error.is_path():
            path_error = error.get_path()
            if hasattr(path_error, "is_not_found") and path_error.is_not_found():
                return True
        return False

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(
            lambda exc: isinstance(exc, ApiError) and not DropboxStorage._is_sidecar_not_found_error(exc)
        ),  # type: ignore[arg-type]
    )
    async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None:
        """
        Download the .txt sidecar for the given image if it exists.

        Returns the sidecar bytes on success, or None when Dropbox reports that
        the sidecar file does not exist. Transient errors remain subject to
        tenacity retries and ultimately surface as ApiError/StorageError.
        """

        try:

            def _download() -> bytes:
                stem = os.path.splitext(filename)[0]
                sidecar_name = f"{stem}.txt"
                path = os.path.join(folder, sidecar_name)
                _, response = self.client.files_download(path)
                return cast(bytes, response.content)

            return await asyncio.to_thread(_download)
        except ApiError as exc:
            if self._is_sidecar_not_found_error(exc):
                # Fast-path for "not found" – treat as normal cache miss instead of error.
                return None
            raise _wrap_dropbox_exception(exc, f"Failed to download sidecar for {filename}") from exc
        except DropboxException as exc:
            raise _wrap_dropbox_exception(exc, f"Failed to download sidecar for {filename}") from exc

    @_dropbox_retry
    async def get_file_metadata(self, folder: str, filename: str) -> FileMetadata:
        """Return normalized file identity/version metadata (#96)."""
        try:

            def _meta() -> FileMetadata:
                path = os.path.join(folder, filename)
                md = self.client.files_get_metadata(path)
                if isinstance(md, dropbox.files.FileMetadata):
                    return FileMetadata(
                        file_id=getattr(md, "id", None) or None,
                        revision=getattr(md, "rev", None) or None,
                        modified_at=str(getattr(md, "server_modified", "") or "") or None,
                        size=getattr(md, "size", None),
                    )
                return FileMetadata()

            return await asyncio.to_thread(_meta)
        except DropboxException as exc:
            raise _wrap_dropbox_exception(exc, f"Failed to get metadata for {filename}") from exc

    @_dropbox_retry
    async def list_images(self, folder: str) -> list[str]:
        try:

            def _list() -> list[str]:
                path = "" if folder == "/" else folder
                result = self.client.files_list_folder(path)
                names: list[str] = []
                while True:
                    for entry in result.entries:
                        if isinstance(entry, dropbox.files.FileMetadata) and entry.name.lower().endswith(
                            (".jpg", ".jpeg", ".png")
                        ):
                            names.append(entry.name)
                    if not result.has_more:
                        break
                    result = self.client.files_list_folder_continue(result.cursor)
                return names

            return await asyncio.to_thread(_list)
        except DropboxException as exc:
            raise _wrap_dropbox_exception(exc, "Failed to list images") from exc

    @_dropbox_retry
    async def list_images_with_hashes(self, folder: str) -> list[tuple[str, str]]:
        """
        Return image filenames and their Dropbox content_hash where available.

        Falls back to the same filtering as list_images but preserves content_hash
        so that the workflow can perform metadata-based de-duplication.
        """
        try:

            def _list() -> list[tuple[str, str]]:
                path = "" if folder == "/" else folder
                result = self.client.files_list_folder(path)
                out: list[tuple[str, str]] = []
                while True:
                    for entry in result.entries:
                        if isinstance(entry, dropbox.files.FileMetadata) and entry.name.lower().endswith(
                            (".jpg", ".jpeg", ".png")
                        ):
                            ch = getattr(entry, "content_hash", None) or ""
                            out.append((entry.name, ch))
                    if not result.has_more:
                        break
                    result = self.client.files_list_folder_continue(result.cursor)
                return out

            return await asyncio.to_thread(_list)
        except DropboxException as exc:
            raise _wrap_dropbox_exception(exc, "Failed to list images with hashes") from exc

    @_dropbox_retry
    async def download_image(self, folder: str, filename: str) -> bytes:
        try:

            def _download() -> bytes:
                path = os.path.join(folder, filename)
                _, response = self.client.files_download(path)
                return cast(bytes, response.content)

            return await asyncio.to_thread(_download)
        except DropboxException as exc:
            raise _wrap_dropbox_exception(exc, f"Failed to download {filename}") from exc

    @_dropbox_retry
    async def get_temporary_link(self, folder: str, filename: str) -> str:
        try:

            def _link() -> str:
                path = os.path.join(folder, filename)
                res = self.client.files_get_temporary_link(path)
                return cast(str, res.link)

            return await asyncio.to_thread(_link)
        except DropboxException as exc:
            raise _wrap_dropbox_exception(exc, f"Failed to get temporary link for {filename}") from exc

    @_dropbox_retry
    async def ensure_folder_exists(self, folder_path: str) -> None:
        """
        Ensure the specified folder exists in Dropbox.
        Creates it if it does not exist; ignores error if it already exists.
        """
        try:

            def _ensure() -> None:
                try:
                    self.client.files_create_folder_v2(folder_path)
                except ApiError as exc:
                    # Check if error is "path already exists"
                    error = getattr(exc, "error", None)
                    if error and error.is_path() and error.get_path().is_conflict():
                        pass
                    else:
                        raise

            await asyncio.to_thread(_ensure)
        except DropboxException as exc:
            raise _wrap_dropbox_exception(exc, f"Failed to ensure folder exists {folder_path}") from exc

    @_dropbox_retry
    async def move_image_with_sidecars(self, folder: str, filename: str, target_subfolder: str) -> None:
        """
        Move the image and its .txt sidecar (if present) into a subfolder under the given folder.

        This is implemented via Dropbox server-side moves and is reused by archive and
        curation-style operations (Keep/Remove).
        """
        try:

            def _move() -> None:
                src = os.path.join(folder, filename)
                dst_dir = _dropbox_move_destination_dir(folder, target_subfolder)
                # Ensure destination folder exists
                with contextlib.suppress(ApiError):
                    self.client.files_create_folder_v2(dst_dir)
                dst = os.path.join(dst_dir, filename)
                self.client.files_move_v2(src, dst, autorename=True)
                # Attempt to move sidecar if present
                sidecar_name = f"{os.path.splitext(filename)[0]}.txt"
                sidecar_src = os.path.join(folder, sidecar_name)
                sidecar_dst = os.path.join(dst_dir, sidecar_name)
                with contextlib.suppress(ApiError):
                    self.client.files_move_v2(sidecar_src, sidecar_dst, autorename=True)

            await asyncio.to_thread(_move)
        except DropboxException as exc:
            raise _wrap_dropbox_exception(exc, f"Failed to move {filename} to {target_subfolder}") from exc

    @_dropbox_retry
    async def delete_file_with_sidecar(self, folder: str, filename: str) -> None:
        """
        Permanently delete an image and its .txt sidecar (if present) from Dropbox.

        This is a destructive operation and cannot be undone.
        """
        try:

            def _delete() -> None:
                # Delete main image file
                path = os.path.join(folder, filename)
                self.client.files_delete_v2(path)

                # Attempt to delete sidecar if present
                sidecar_name = f"{os.path.splitext(filename)[0]}.txt"
                sidecar_path = os.path.join(folder, sidecar_name)
                with contextlib.suppress(ApiError):
                    self.client.files_delete_v2(sidecar_path)

            await asyncio.to_thread(_delete)
        except DropboxException as exc:
            raise _wrap_dropbox_exception(exc, f"Failed to delete {filename}") from exc

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        """
        Archive an image (and its sidecar) into the configured archive folder.

        Internally delegates to move_image_with_sidecars to keep Dropbox move
        semantics in one place.
        """
        await self.move_image_with_sidecars(folder, filename, archive_folder)

    # #96: object-level operations are managed-storage-only; the library UI
    # is guarded by _check_library_available and never reaches Dropbox.
    async def list_objects(self, prefix: str, cursor: str | None = None, limit: int = 1000) -> dict:
        raise StorageNotSupportedError("DropboxStorage does not support object-level listing")

    async def put_object(self, key: str, data: bytes, content_type: str) -> None:
        raise StorageNotSupportedError("DropboxStorage does not support object-level put")

    async def head_object(self, key: str) -> dict | None:
        raise StorageNotSupportedError("DropboxStorage does not support object-level head")

    async def delete_object(self, key: str) -> None:
        raise StorageNotSupportedError("DropboxStorage does not support object-level delete")

    async def move_object(self, src_key: str, dst_key: str) -> None:
        raise StorageNotSupportedError("DropboxStorage does not support object-level move")

    def supports_content_hashing(self) -> bool:
        """Dropbox supports content-hash-based dedup via content_hash metadata."""
        return True

    # Mapping from protocol-level enum string values to Dropbox SDK enums
    _THUMB_SIZE_MAP: dict[str, DbxThumbnailSize] = {
        "w256h256": DbxThumbnailSize.w256h256,
        "w480h320": DbxThumbnailSize.w480h320,
        "w640h480": DbxThumbnailSize.w640h480,
        "w960h640": DbxThumbnailSize.w960h640,
        "w1024h768": DbxThumbnailSize.w1024h768,
    }
    _THUMB_FMT_MAP: dict[str, DbxThumbnailFormat] = {
        "jpeg": DbxThumbnailFormat.jpeg,
        "png": DbxThumbnailFormat.png,
    }

    @_dropbox_retry
    async def get_thumbnail(
        self,
        folder: str,
        filename: str,
        size: ThumbnailSize | DbxThumbnailSize = ThumbnailSize.W960H640,
        format: ThumbnailFormat | DbxThumbnailFormat = ThumbnailFormat.JPEG,
    ) -> bytes:
        """
        Return a thumbnail of the specified image using Dropbox's thumbnail API.

        Accepts protocol-level ThumbnailSize/ThumbnailFormat enums and maps
        them to Dropbox SDK enums internally. Also accepts Dropbox SDK enums
        directly for backward compatibility.
        """
        if isinstance(size, DbxThumbnailSize):
            dbx_size = size
        else:
            dbx_size = self._THUMB_SIZE_MAP.get(str(size), DbxThumbnailSize.w960h640)
        if isinstance(format, DbxThumbnailFormat):
            dbx_format = format
        else:
            dbx_format = self._THUMB_FMT_MAP.get(str(format), DbxThumbnailFormat.jpeg)

        try:

            def _get_thumb() -> bytes:
                path = os.path.join(folder, filename)
                _, response = self.client.files_get_thumbnail_v2(
                    resource=PathOrLink.path(path),
                    size=dbx_size,
                    format=dbx_format,
                    mode=ThumbnailMode.fitone_bestfit,
                )
                return cast(bytes, response.content)

            return await asyncio.to_thread(_get_thumb)
        except DropboxException as exc:
            raise _wrap_dropbox_exception(exc, f"Failed to get thumbnail for {filename}") from exc
