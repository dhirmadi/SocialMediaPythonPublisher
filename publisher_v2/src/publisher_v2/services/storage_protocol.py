"""Storage protocol — formal interface for all storage backends.

Defines the structural contract that storage implementations (e.g. DropboxStorage)
must satisfy. Consumers type-hint against StorageProtocol, not concrete classes.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable


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

    async def get_file_metadata(self, folder: str, filename: str) -> dict[str, str]: ...

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
