from __future__ import annotations

import pytest

from publisher_v2.config.schema import DropboxConfig
from publisher_v2.services.storage import DropboxStorage

# Use centralized test fixtures from conftest.py (QC-001)
from conftest import BaseDummyClient


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
    # Use centralized fixture (QC-001)
    client = BaseDummyClient()
    monkeypatch.setattr(storage, "client", client)

    await storage.archive_image("/ImagesToday", "image.jpg", "archive")

    expected_moves = {
        ("/ImagesToday/image.jpg", "/ImagesToday/archive/image.jpg"),
        ("/ImagesToday/image.txt", "/ImagesToday/archive/image.txt"),
    }
    assert set(client.moves) >= expected_moves


