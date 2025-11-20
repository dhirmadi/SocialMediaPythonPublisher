from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List, Optional

import pytest
from dropbox.exceptions import ApiError

from publisher_v2.config.schema import DropboxConfig
from publisher_v2.services.storage import DropboxStorage


class DummyClient:
    def __init__(self) -> None:
        self.uploads: List[tuple[str, bytes, Any]] = []
        self.sidecar_bytes: Optional[bytes] = None
        self.sidecar_exists: bool = True

    def files_upload(self, data: bytes, path: str, mode: Any, mute: bool = False, strict_conflict: bool = False) -> None:
        self.uploads.append((path, data, mode))

    def files_download(self, path: str) -> tuple[None, SimpleNamespace]:
        # Simple emulation: only support sidecar path, and respect sidecar_exists flag.
        if not self.sidecar_exists:
            # Build a minimal ApiError with a .error exposing is_path()/get_path().is_not_found()
            class _PathError:
                def is_not_found(self) -> bool:
                    return True

            class _Error:
                def is_path(self) -> bool:
                    return True

                def get_path(self) -> _PathError:
                    return _PathError()

            raise ApiError("request-id", _Error(), "not_found", "en-US")
        content = self.sidecar_bytes or b"sidecar-bytes"
        return None, SimpleNamespace(content=content)


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
    dummy = DummyClient()
    dummy.sidecar_bytes = b"hello-sidecar"
    dummy.sidecar_exists = True
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
    dummy = DummyClient()
    dummy.sidecar_exists = False
    monkeypatch.setattr(storage, "client", dummy)

    blob = await storage.download_sidecar_if_exists("/ImagesToday", "image.jpg")
    assert blob is None

