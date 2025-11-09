from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List

import pytest

from publisher_v2.config.schema import DropboxConfig
from publisher_v2.services.storage import DropboxStorage


class DummyClient:
    def __init__(self) -> None:
        self.uploads: List[tuple[str, bytes, Any]] = []

    def files_upload(self, data: bytes, path: str, mode: Any, mute: bool = False, strict_conflict: bool = False) -> None:
        self.uploads.append((path, data, mode))


@pytest.mark.asyncio
async def test_sidecar_upload_overwrite(monkeypatch: pytest.MonkeyPatch) -> None:
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

    await storage.write_sidecar_text("/ImagesToday", "image.jpg", "sd caption")

    assert len(dummy.uploads) == 1
    path, data, mode = dummy.uploads[0]
    assert path == "/ImagesToday/image.txt"
    assert data.decode("utf-8") == "sd caption"

