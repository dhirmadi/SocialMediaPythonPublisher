from __future__ import annotations

from typing import List, Tuple

import pytest

from publisher_v2.config.schema import DropboxConfig
from publisher_v2.services.storage import DropboxStorage


class DummyClient:
    def __init__(self) -> None:
        self.moves: List[Tuple[str, str]] = []
        self.created: List[str] = []

    def files_create_folder_v2(self, path: str) -> None:
        self.created.append(path)

    def files_move_v2(self, src: str, dst: str, autorename: bool = False) -> None:
        # record moves; ignore not-found for sidecar by simply recording
        self.moves.append((src, dst))


@pytest.mark.asyncio
async def test_archive_moves_image_and_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = DropboxConfig(
        app_key="key",
        app_secret="secret",
        refresh_token="refresh",
        image_folder="/ImagesToday",
        archive_folder="archive",
    )
    storage = DropboxStorage(cfg)
    client = DummyClient()
    monkeypatch.setattr(storage, "client", client)

    await storage.archive_image("/ImagesToday", "image.jpg", "archive")

    expected_moves = {
        ("/ImagesToday/image.jpg", "/ImagesToday/archive/image.jpg"),
        ("/ImagesToday/image.txt", "/ImagesToday/archive/image.txt"),
    }
    assert set(client.moves) >= expected_moves


