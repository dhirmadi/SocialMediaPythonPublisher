from __future__ import annotations

from types import SimpleNamespace
from typing import List, Optional

import pytest
from dropbox.exceptions import ApiError

from publisher_v2.config.schema import DropboxConfig
from publisher_v2.services.storage import DropboxStorage


class DummyClient:
    def __init__(self) -> None:
        self.created_dirs: List[str] = []
        self.moves: List[tuple[str, str]] = []
        self.sidecar_exists: bool = True

    def files_create_folder_v2(self, path: str) -> None:
        self.created_dirs.append(path)

    def files_move_v2(self, from_path: str, to_path: str, autorename: bool = False) -> None:
        # Simulate sidecar missing by raising ApiError when appropriate.
        if from_path.endswith("image.txt") and not self.sidecar_exists:
            class _Error:
                def is_path(self) -> bool:
                    return True

                def get_path(self) -> SimpleNamespace:
                    return SimpleNamespace(is_not_found=lambda: True)

            raise ApiError("req", _Error(), "not_found", "en-US")
        self.moves.append((from_path, to_path))


@pytest.mark.asyncio
async def test_move_image_with_sidecars_moves_image_and_txt(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = DropboxConfig(
        app_key="key",
        app_secret="secret",
        refresh_token="refresh",
        image_folder="/ImagesToday",
        archive_folder="archive",
    )
    storage = DropboxStorage(cfg)
    dummy = DummyClient()
    monkeypatch.setattr(storage, "client", dummy)

    await storage.move_image_with_sidecars("/ImagesToday", "image.jpg", "keep")

    # Ensure destination directory created and both image and sidecar moved.
    assert "/ImagesToday/keep" in dummy.created_dirs
    assert ("/ImagesToday/image.jpg", "/ImagesToday/keep/image.jpg") in dummy.moves
    assert ("/ImagesToday/image.txt", "/ImagesToday/keep/image.txt") in dummy.moves


@pytest.mark.asyncio
async def test_move_image_with_sidecars_ignores_missing_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = DropboxConfig(
        app_key="key",
        app_secret="secret",
        refresh_token="refresh",
        image_folder="/ImagesToday",
        archive_folder="archive",
    )
    storage = DropboxStorage(cfg)
    dummy = DummyClient()
    dummy.sidecar_exists = False
    monkeypatch.setattr(storage, "client", dummy)

    # Should not raise when sidecar is missing; only the image must move.
    await storage.move_image_with_sidecars("/ImagesToday", "image.jpg", "keep")

    assert ("/ImagesToday/image.jpg", "/ImagesToday/keep/image.jpg") in dummy.moves


@pytest.mark.asyncio
async def test_archive_image_delegates_to_move_image_with_sidecars(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = DropboxConfig(
        app_key="key",
        app_secret="secret",
        refresh_token="refresh",
        image_folder="/ImagesToday",
        archive_folder="archive",
    )
    storage = DropboxStorage(cfg)

    called: dict[str, Optional[tuple[str, str, str]]] = {"args": None}

    async def _fake_move(folder: str, filename: str, target: str) -> None:
        called["args"] = (folder, filename, target)

    monkeypatch.setattr(storage, "move_image_with_sidecars", _fake_move)

    await storage.archive_image("/ImagesToday", "image.jpg", "archive")

    assert called["args"] == ("/ImagesToday", "image.jpg", "archive")


