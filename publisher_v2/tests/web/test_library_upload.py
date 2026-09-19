"""SEC-6 (#90): upload must rate-limit and size-check before buffering the body."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from PIL import Image
from starlette.requests import Request

from publisher_v2.web.routers import library


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    library._upload_rate_limit.clear()
    yield
    library._upload_rate_limit.clear()


@pytest.fixture(autouse=True)
def _bypass_auth(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(library, "require_auth", AsyncMock())
    monkeypatch.setattr(library, "require_admin", lambda request: None)


def _request(content_length: int | None = None) -> Request:
    headers = [(b"cookie", b"pv2_admin=x")]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    return Request({"type": "http", "method": "POST", "path": "/api/library/upload", "headers": headers})


def _service() -> MagicMock:
    service = MagicMock()
    service.config.managed = MagicMock()
    service.config.features.library_enabled = True
    return service


class _CountingFile:
    """Fake UploadFile: yields 1 MiB chunks forever, counts reads."""

    filename = "big.jpg"

    def __init__(self, chunk: bytes = b"x" * (1024 * 1024)) -> None:
        self.reads = 0
        self._chunk = chunk

    async def read(self, size: int = -1) -> bytes:
        self.reads += 1
        return self._chunk


def _png_bytes(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    with Image.new("L", (width, height), color=255) as img:
        img.save(buf, format="PNG")
    return buf.getvalue()


class _RealFile:
    def __init__(self, data: bytes, filename: str = "img.png") -> None:
        self._buf = io.BytesIO(data)
        self.filename = filename

    async def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)


class TestBoundedBuffering:
    async def test_body_over_cap_aborts_early_with_413(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LIBRARY_MAX_UPLOAD_MB", "2")
        file = _CountingFile()

        with pytest.raises(HTTPException) as exc_info:
            await library.upload_file(_request(), file, _service())  # type: ignore[arg-type]

        assert exc_info.value.status_code == 413
        # 2 MiB cap with 1 MiB chunks: aborted after ~3 reads, not the whole body.
        assert file.reads <= 4

    async def test_content_length_over_cap_rejected_before_any_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LIBRARY_MAX_UPLOAD_MB", "2")
        file = _CountingFile()

        with pytest.raises(HTTPException) as exc_info:
            await library.upload_file(_request(content_length=3 * 1024 * 1024), file, _service())  # type: ignore[arg-type]

        assert exc_info.value.status_code == 413
        assert file.reads == 0

    async def test_rate_limit_consumed_before_any_body_bytes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _limit_hit(request: Request) -> None:
            raise HTTPException(status_code=429, detail="rate limited")

        monkeypatch.setattr(library, "_check_rate_limit", _limit_hit)
        file = _CountingFile()

        with pytest.raises(HTTPException) as exc_info:
            await library.upload_file(_request(), file, _service())  # type: ignore[arg-type]

        assert exc_info.value.status_code == 429
        assert file.reads == 0


class TestImageSafety:
    async def test_decompression_bomb_returns_415(self, monkeypatch: pytest.MonkeyPatch) -> None:
        data = _png_bytes(100, 100)  # 10k pixels
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)  # Error threshold = 2x = 2000 px

        with pytest.raises(HTTPException) as exc_info:
            await library.upload_file(_request(), _RealFile(data), _service())  # type: ignore[arg-type]

        assert exc_info.value.status_code == 415

    async def test_oversized_dimensions_return_415(self) -> None:
        data = _png_bytes(12_001, 2)

        with pytest.raises(HTTPException) as exc_info:
            await library.upload_file(_request(), _RealFile(data), _service())  # type: ignore[arg-type]

        assert exc_info.value.status_code == 415

    async def test_verification_runs_in_thread(self, monkeypatch: pytest.MonkeyPatch) -> None:
        data = _png_bytes(10, 10)
        threaded: list[str] = []
        import asyncio as _asyncio

        real_to_thread = _asyncio.to_thread

        async def _spy(fn, *args, **kwargs):
            threaded.append(getattr(fn, "__name__", str(fn)))
            return await real_to_thread(fn, *args, **kwargs)

        monkeypatch.setattr(library.asyncio, "to_thread", _spy)
        with patch.object(library, "_upload_to_storage", new=AsyncMock(return_value={"key": "k", "size": 1})):
            result = await library.upload_file(_request(), _RealFile(data), _service())  # type: ignore[arg-type]

        assert result.key == "k"
        assert "_verify_image_bytes" in threaded


def test_max_image_pixels_configured_at_import() -> None:
    """#90: Pillow's global bomb threshold is pinned by utils.images."""
    import publisher_v2.utils.images  # noqa: F401

    assert Image.MAX_IMAGE_PIXELS == 40_000_000
