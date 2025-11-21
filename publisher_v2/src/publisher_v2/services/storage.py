from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import List, Tuple, Optional

import dropbox
from dropbox.exceptions import ApiError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from publisher_v2.config.schema import DropboxConfig
from publisher_v2.core.exceptions import StorageError


class DropboxStorage:
    def __init__(self, config: DropboxConfig):
        self.config = config
        self.client = dropbox.Dropbox(
            oauth2_refresh_token=config.refresh_token,
            app_key=config.app_key,
            app_secret=config.app_secret,
        )

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
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
        except ApiError as exc:
            raise StorageError(f"Failed to upload sidecar for {filename}: {exc}") from exc

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
        retry=retry_if_exception(lambda exc: isinstance(exc, ApiError) and not DropboxStorage._is_sidecar_not_found_error(exc)),  # type: ignore[arg-type]
    )
    async def download_sidecar_if_exists(self, folder: str, filename: str) -> Optional[bytes]:
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
                return response.content

            return await asyncio.to_thread(_download)
        except ApiError as exc:
            if self._is_sidecar_not_found_error(exc):
                # Fast-path for "not found" – treat as normal cache miss instead of error.
                return None
            raise StorageError(f"Failed to download sidecar for {filename}: {exc}") from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    async def get_file_metadata(self, folder: str, filename: str) -> dict[str, str]:
        """
        Return minimal Dropbox file metadata for identity/version fields.
        Keys: id, rev. Missing values omitted.
        """
        try:
            def _meta() -> dict[str, str]:
                path = os.path.join(folder, filename)
                md = self.client.files_get_metadata(path)
                out: dict[str, str] = {}
                if isinstance(md, dropbox.files.FileMetadata):
                    if getattr(md, "id", None):
                        out["id"] = md.id
                    if getattr(md, "rev", None):
                        out["rev"] = md.rev
                return out

            return await asyncio.to_thread(_meta)
        except ApiError as exc:
            raise StorageError(f"Failed to get metadata for {filename}: {exc}") from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    async def list_images(self, folder: str) -> List[str]:
        try:
            def _list() -> List[str]:
                path = "" if folder == "/" else folder
                result = self.client.files_list_folder(path)
                names: List[str] = []
                for entry in result.entries:
                    if isinstance(entry, dropbox.files.FileMetadata):
                        name = entry.name.lower()
                        if name.endswith((".jpg", ".jpeg", ".png")):
                            names.append(entry.name)
                return names

            return await asyncio.to_thread(_list)
        except ApiError as exc:
            raise StorageError(f"Failed to list images: {exc}") from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    async def list_images_with_hashes(self, folder: str) -> List[Tuple[str, str]]:
        """
        Return image filenames and their Dropbox content_hash where available.

        Falls back to the same filtering as list_images but preserves content_hash
        so that the workflow can perform metadata-based de-duplication.
        """
        try:
            def _list() -> List[Tuple[str, str]]:
                path = "" if folder == "/" else folder
                result = self.client.files_list_folder(path)
                out: List[Tuple[str, str]] = []
                for entry in result.entries:
                    if isinstance(entry, dropbox.files.FileMetadata):
                        name_lower = entry.name.lower()
                        if name_lower.endswith((".jpg", ".jpeg", ".png")):
                            ch = getattr(entry, "content_hash", None) or ""
                            out.append((entry.name, ch))
                return out

            return await asyncio.to_thread(_list)
        except ApiError as exc:
            raise StorageError(f"Failed to list images with hashes: {exc}") from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    async def download_image(self, folder: str, filename: str) -> bytes:
        try:
            def _download() -> bytes:
                path = os.path.join(folder, filename)
                _, response = self.client.files_download(path)
                return response.content

            return await asyncio.to_thread(_download)
        except ApiError as exc:
            raise StorageError(f"Failed to download {filename}: {exc}") from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    async def get_temporary_link(self, folder: str, filename: str) -> str:
        try:
            def _link() -> str:
                path = os.path.join(folder, filename)
                res = self.client.files_get_temporary_link(path)
                return res.link

            return await asyncio.to_thread(_link)
        except ApiError as exc:
            raise StorageError(f"Failed to get temporary link for {filename}: {exc}") from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    async def move_image_with_sidecars(self, folder: str, filename: str, target_subfolder: str) -> None:
        """
        Move the image and its .txt sidecar (if present) into a subfolder under the given folder.

        This is implemented via Dropbox server-side moves and is reused by archive and
        curation-style operations (Keep/Remove).
        """
        try:
            def _move() -> None:
                src = os.path.join(folder, filename)
                dst_dir = os.path.join(folder, target_subfolder)
                # Ensure destination folder exists
                try:
                    self.client.files_create_folder_v2(dst_dir)
                except ApiError:
                    # Already exists or cannot create; ignore if exists
                    pass
                dst = os.path.join(dst_dir, filename)
                self.client.files_move_v2(src, dst, autorename=True)
                # Attempt to move sidecar if present
                sidecar_name = f"{os.path.splitext(filename)[0]}.txt"
                sidecar_src = os.path.join(folder, sidecar_name)
                sidecar_dst = os.path.join(dst_dir, sidecar_name)
                try:
                    self.client.files_move_v2(sidecar_src, sidecar_dst, autorename=True)
                except ApiError:
                    # Sidecar may not exist; ignore
                    pass

            await asyncio.to_thread(_move)
        except ApiError as exc:
            raise StorageError(f"Failed to move {filename} to {target_subfolder}: {exc}") from exc

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        """
        Archive an image (and its sidecar) into the configured archive folder.

        Internally delegates to move_image_with_sidecars to keep Dropbox move
        semantics in one place.
        """
        await self.move_image_with_sidecars(folder, filename, archive_folder)
