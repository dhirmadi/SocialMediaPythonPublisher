from __future__ import annotations

import pytest

from publisher_v2.config.schema import DropboxConfig
from publisher_v2.services.storage import DropboxStorage

# Use centralized test fixtures from conftest.py (QC-001)
from conftest import BaseDummyClient


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
    # Use centralized fixture (QC-001)
    dummy = BaseDummyClient()
    monkeypatch.setattr(storage, "client", dummy)

    await storage.write_sidecar_text("/ImagesToday", "image.jpg", "sd caption")

    assert len(dummy.uploads) == 1
    path, data, mode = dummy.uploads[0]
    assert path == "/ImagesToday/image.txt"
    assert data.decode("utf-8") == "sd caption"


@pytest.mark.asyncio
async def test_download_sidecar_if_exists_returns_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = DropboxConfig(
        app_key="key",
        app_secret="secret",
        refresh_token="refresh",
        image_folder="/ImagesToday",
        archive_folder="archive",
    )
    storage = DropboxStorage(cfg)
    # Use centralized fixture (QC-001)
    dummy = BaseDummyClient(sidecar_exists=True)
    dummy.sidecar_bytes = b"hello-sidecar"
    monkeypatch.setattr(storage, "client", dummy)

    blob = await storage.download_sidecar_if_exists("/ImagesToday", "image.jpg")
    assert blob == b"hello-sidecar"


@pytest.mark.asyncio
async def test_download_sidecar_if_exists_returns_none_on_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = DropboxConfig(
        app_key="key",
        app_secret="secret",
        refresh_token="refresh",
        image_folder="/ImagesToday",
        archive_folder="archive",
    )
    storage = DropboxStorage(cfg)
    # Use centralized fixture (QC-001)
    dummy = BaseDummyClient(sidecar_exists=False)
    monkeypatch.setattr(storage, "client", dummy)

    blob = await storage.download_sidecar_if_exists("/ImagesToday", "image.jpg")
    assert blob is None

