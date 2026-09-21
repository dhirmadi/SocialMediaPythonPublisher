"""Storage protocol — formal interface for all storage backends.

Defines the structural contract that storage implementations (e.g. DropboxStorage)
must satisfy. Consumers type-hint against StorageProtocol, not concrete classes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class FileMetadata:
    """Backend-agnostic file identity/version metadata (#96).

    Dropbox populates file_id/revision from id/rev; managed storage populates
    revision from the object ETag and modified_at/size from head_object.
    """

    file_id: str | None = None
    revision: str | None = None
    modified_at: str | None = None
    size: int | None = None


class ThumbnailSize(StrEnum):
    """Protocol-level thumbnail sizes matching the web API's ThumbnailSizeParam."""

    W256H256 = "w256h256"
    W480H320 = "w480h320"
    W640H480 = "w640h480"
    W960H640 = "w960h640"
    W1024H768 = "w1024h768"


class ThumbnailFormat(StrEnum):
    """Protocol-level thumbnail output formats."""

    JPEG = "jpeg"
    PNG = "png"


@runtime_checkable
class StorageProtocol(Protocol):
    """Structural protocol for storage backends.

    All public methods consumed by WorkflowOrchestrator, WebImageService,
    and sidecar utilities. Implementations satisfy this via structural
    subtyping (duck typing) — no explicit inheritance required.
    """

    async def list_images(self, folder: str) -> list[str]:
        """Return the image filenames directly inside ``folder``.

        Only immediate children count — objects in nested sub-prefixes are
        skipped — and only image extensions (.jpg/.jpeg/.png) are returned.
        Names are bare filenames, not paths. Implementations must page through
        the whole folder before returning, and must raise ``StorageError`` on
        backend failure. Every request issued here is metered (PUB-045).
        """
        ...

    async def list_images_with_hashes(self, folder: str) -> list[tuple[str, str]]:
        """Return ``(filename, content_hash)`` for each image directly inside ``folder``.

        Same filtering as ``list_images``. The hash is backend-defined (Dropbox
        content_hash, ETag for managed storage) and is only meaningful as an
        equality token for change detection — never compare across backends.
        Callers must gate on ``supports_content_hashing()`` first.
        """
        ...

    async def download_image(self, folder: str, filename: str) -> bytes:
        """Return the full bytes of ``folder/filename``.

        Implementations must verify the transfer is complete (truncated bodies
        raise ``StorageError`` rather than returning short data) and must raise
        ``StorageError`` when the object is missing or the backend fails.
        """
        ...

    async def get_temporary_link(self, folder: str, filename: str) -> str:
        """Return a short-lived, unauthenticated direct-download URL for the image.

        The link expires (one hour for managed storage, backend-defined for
        Dropbox), so it must be handed to the client and not cached or logged.
        Raises ``StorageError`` if the link cannot be issued.
        """
        ...

    async def get_file_metadata(self, folder: str, filename: str) -> FileMetadata:
        """Return normalized identity/version metadata for the image (#96).

        Fields the backend cannot supply are left as None rather than faked, so
        callers must treat every field as optional. Raises ``StorageError`` when
        the lookup fails.
        """
        ...

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        """Write (overwriting) the UTF-8 .txt sidecar beside the image.

        The sidecar name is the image stem plus ``.txt`` — for ``image.jpg`` it
        writes ``image.txt`` — so the caller passes the *image* filename, not
        the sidecar's. Raises ``StorageError`` on failure.
        """
        ...

    async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None:
        """Return the image's .txt sidecar bytes, or None when there is no sidecar.

        A missing sidecar is a normal outcome and must not raise; any other
        backend failure surfaces as ``StorageError``. Callers pass the image
        filename, as in ``write_sidecar_text``.
        """
        ...

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        """Move the image and its sidecar out of ``folder`` into ``archive_folder``.

        Server-side move; the sidecar is best-effort (a missing one is not an
        error). Must never be called from preview mode. Raises ``StorageError``
        if the image itself cannot be moved.
        """
        ...

    async def move_image_with_sidecars(self, folder: str, filename: str, target_subfolder: str) -> None:
        """Move the image and its .txt sidecar into ``target_subfolder`` under ``folder``.

        Backs the curation actions (Keep/Remove) and archiving. The destination
        is created if needed; the sidecar move is best-effort. Raises
        ``StorageError`` when the image move fails.
        """
        ...

    async def delete_file_with_sidecar(self, folder: str, filename: str) -> None:
        """Permanently delete the image and its .txt sidecar.

        Destructive and not undoable — no trash, no restore. The sidecar delete
        is best-effort; failure to delete the image raises ``StorageError``.
        """
        ...

    async def ensure_folder_exists(self, folder_path: str) -> None:
        """Ensure ``folder_path`` exists, creating it if needed.

        Idempotent: an existing folder is not an error. Object stores have no
        real folders, so managed storage implements this as a no-op.
        """
        ...

    async def get_thumbnail(
        self,
        folder: str,
        filename: str,
        size: ThumbnailSize = ThumbnailSize.W960H640,
        format: ThumbnailFormat = ThumbnailFormat.JPEG,
    ) -> bytes:
        """Return encoded thumbnail bytes for the image in the requested size and format.

        The size is an upper bound, not an exact output dimension. Backends may
        serve this from a cache that must be invalidated whenever the underlying
        object is written, moved or deleted. Raises ``StorageError`` on failure.
        """
        ...

    def supports_content_hashing(self) -> bool:
        """Return True when this backend can supply per-file content hashes.

        Gates use of ``list_images_with_hashes`` — callers must fall back to
        name-based logic when this is False. Synchronous and side-effect free.
        """
        ...


class StorageNotSupportedError(NotImplementedError):
    """Raised by backends that do not implement an object-level operation (#96)."""


@runtime_checkable
class ObjectStorageProtocol(Protocol):
    """Object-level operations used by the admin library router (#96).

    ``ManagedStorage`` implements all of these (with PUB-045 metering inside);
    ``DropboxStorage`` raises ``StorageNotSupportedError`` — the library UI is
    managed-storage-only by design.
    """

    async def list_objects(self, prefix: str, cursor: str | None = None, limit: int = 1000) -> dict[str, Any]:
        """One listing page: {"items": [{key, size, last_modified}], "cursor": str|None, "is_truncated": bool}.

        Lists immediate children of ``prefix`` only (delimited listing), at most
        ``limit`` (capped at 1000) per call. Pass the returned ``cursor`` back to
        fetch the next page; it is None once ``is_truncated`` is False. Each page
        is one billable, metered request. Raises ``StorageError`` on failure and
        ``StorageNotSupportedError`` on backends without object-level access.
        """
        ...

    async def put_object(self, key: str, data: bytes | bytearray | memoryview, content_type: str) -> None:
        """Write ``data`` at the absolute object ``key`` with the given content type.

        Overwrites any existing object and invalidates cached thumbnails for the
        key, including when the write fails. ``key`` is a full object key, not a
        folder/filename pair. Raises ``StorageError``, or
        ``StorageNotSupportedError`` on backends without object-level access.
        """
        ...

    async def head_object(self, key: str) -> dict[str, Any] | None:
        """Metadata dict for the object, or None when it does not exist.

        The dict carries ``size``, ``etag`` and ``last_modified``. Note that a
        non-404 failure (403, throttling) is logged and also reported as None,
        so None means "not visible", not strictly "absent". Costs one metered
        request. Raises ``StorageNotSupportedError`` on backends without
        object-level access.
        """
        ...

    async def exists(self, key: str) -> bool:
        """True when the object is present (#142: resume without reading metadata shapes).

        Implemented as a single metered ``head_object``, so it inherits its
        "not visible reads as absent" caveat. Raises
        ``StorageNotSupportedError`` on backends without object-level access.
        """
        ...

    async def delete_object(self, key: str) -> None:
        """Delete the object at ``key``, permanently and without a trash step.

        Deleting a missing key is not an error for S3-compatible backends.
        Cached thumbnails for the key are invalidated even if the delete fails.
        Raises ``StorageError``, or ``StorageNotSupportedError`` on backends
        without object-level access.
        """
        ...

    async def move_object(self, src_key: str, dst_key: str) -> None:
        """Move the object from ``src_key`` to ``dst_key`` (server-side copy then delete).

        Not atomic: a failure between the two steps can leave the copy in place.
        Costs two metered requests and invalidates cached thumbnails for both
        keys. Raises ``StorageError``, or ``StorageNotSupportedError`` on
        backends without object-level access.
        """
        ...
