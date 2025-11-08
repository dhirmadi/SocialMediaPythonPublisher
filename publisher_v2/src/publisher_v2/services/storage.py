from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import List

import dropbox
from dropbox.exceptions import ApiError
from tenacity import retry, stop_after_attempt, wait_exponential

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
    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        try:
            def _archive() -> None:
                src = os.path.join(folder, filename)
                dst_dir = os.path.join(folder, archive_folder)
                # Ensure archive folder exists
                try:
                    self.client.files_create_folder_v2(dst_dir)
                except ApiError:
                    # Already exists or cannot create; ignore if exists
                    pass
                dst = os.path.join(dst_dir, filename)
                self.client.files_move_v2(src, dst, autorename=True)

            await asyncio.to_thread(_archive)
        except ApiError as exc:
            raise StorageError(f"Failed to archive {filename}: {exc}") from exc


