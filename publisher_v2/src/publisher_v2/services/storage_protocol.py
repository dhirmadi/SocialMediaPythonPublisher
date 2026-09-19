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

    async def list_images(self, folder: str) -> list[str]: ...

    async def list_images_with_hashes(self, folder: str) -> list[tuple[str, str]]: ...

    async def download_image(self, folder: str, filename: str) -> bytes: ...

    async def get_temporary_link(self, folder: str, filename: str) -> str: ...

    async def get_file_metadata(self, folder: str, filename: str) -> FileMetadata: ...

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None: ...

    async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None: ...

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None: ...

    async def move_image_with_sidecars(self, folder: str, filename: str, target_subfolder: str) -> None: ...

    async def delete_file_with_sidecar(self, folder: str, filename: str) -> None: ...

    async def ensure_folder_exists(self, folder_path: str) -> None: ...

    async def get_thumbnail(
        self,
        folder: str,
        filename: str,
        size: ThumbnailSize = ThumbnailSize.W960H640,
        format: ThumbnailFormat = ThumbnailFormat.JPEG,
    ) -> bytes: ...

    def supports_content_hashing(self) -> bool: ...


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
        """One listing page: {"items": [{key, size, last_modified}], "cursor": str|None, "is_truncated": bool}."""
        ...

    async def put_object(self, key: str, data: bytes | bytearray | memoryview, content_type: str) -> None: ...

    async def head_object(self, key: str) -> dict[str, Any] | None:
        """Metadata dict for the object, or None when it does not exist."""
        ...

    async def exists(self, key: str) -> bool:
        """True when the object is present (#142: resume without reading metadata shapes)."""
        ...

    async def delete_object(self, key: str) -> None: ...

    async def move_object(self, src_key: str, dst_key: str) -> None: ...
