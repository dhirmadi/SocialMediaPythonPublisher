"""SEC-6 (#90): upload must rate-limit and size-check before buffering the body.

#136: these used to call ``library.upload_file(request, file, service)`` directly
with a fake UploadFile — which could not see that FastAPI parsed and spooled the
whole multipart body before the handler ran. They now go through the real app
(``library_upload`` fixture: real app, env-first managed storage, boto3 faked).
"""

from __future__ import annotations

import time

import pytest
from PIL import Image

from publisher_v2.web.routers import library

CAP = 2 * 1024 * 1024  # LIBRARY_MAX_UPLOAD_MB=2 in the fixture


class TestBoundedBuffering:
    async def test_body_over_cap_aborts_early_with_413(self, library_upload) -> None:
        body = library_upload.body(library_upload.png(10, 10), pad_to=3 * CAP)
        res = await library_upload.post(body)
        assert res.status_code == 413
        # Aborted just past the cap, not after the whole body.
        assert body.pulled < len(body.data)
        assert body.pulled <= CAP + 256 * 1024

    async def test_content_length_over_cap_rejected_before_any_read(self, library_upload) -> None:
        body = library_upload.body(library_upload.png(10, 10))
        res = await library_upload.post(body, headers={"Content-Length": str(3 * CAP)})
        assert res.status_code == 413
        assert body.pulled == 0

    async def test_rate_limit_consumed_before_any_body_bytes(self, library_upload) -> None:
        from publisher_v2.web.auth import mint_admin_cookie_value

        cookie = mint_admin_cookie_value(host="testserver")
        library._upload_rate_limit[cookie] = [time.time()] * library._RATE_LIMIT_MAX
        body = library_upload.body(library_upload.png(10, 10))
        res = await library_upload.post(body, cookie=cookie)
        assert res.status_code == 429
        assert body.pulled == 0


class TestImageSafety:
    async def test_decompression_bomb_returns_415(self, library_upload, monkeypatch: pytest.MonkeyPatch) -> None:
        data = library_upload.png(100, 100, mode="L")  # 10k pixels
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)  # Error threshold = 2x = 2000 px
        res = await library_upload.post(library_upload.body(data))
        assert res.status_code == 415
        assert library_upload.s3.puts == []

    async def test_oversized_dimensions_return_415(self, library_upload) -> None:
        res = await library_upload.post(library_upload.body(library_upload.png(12_001, 2, mode="L")))
        assert res.status_code == 415
        assert library_upload.s3.puts == []

    async def test_verification_runs_in_thread(self, library_upload, monkeypatch: pytest.MonkeyPatch) -> None:
        threaded: list[str] = []
        import asyncio as _asyncio

        real_to_thread = _asyncio.to_thread

        async def _spy(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
            threaded.append(getattr(fn, "__name__", str(fn)))
            return await real_to_thread(fn, *args, **kwargs)

        monkeypatch.setattr(library.asyncio, "to_thread", _spy)
        res = await library_upload.post(library_upload.body(library_upload.png(10, 10), filename="t.png"))

        assert res.status_code == 200, res.text
        assert res.json()["key"] == "tenant/instance/t.png"
        assert "_verify_image_bytes" in threaded


class TestSuffixAndOverwrite:
    """PUB-048 (#188) AC8/AC9: the destination key's suffix, and explicit overwrite."""

    async def test_upload_named_txt_with_valid_jpeg_bytes_returns_415(self, library_upload) -> None:
        """AC8: valid image bytes under a sidecar name must never be written."""
        body = library_upload.body(library_upload.png(10, 10), filename="foo.txt")

        res = await library_upload.post(body)

        assert res.status_code == 415, res.text
        assert library_upload.s3.puts == []

    async def test_upload_existing_name_without_overwrite_query_param_returns_409(self, library_upload) -> None:
        """AC9: a silent overwrite of an existing image is a data-loss bug."""
        first = await library_upload.post(library_upload.body(library_upload.png(10, 10), filename="a.jpg"))
        assert first.status_code == 200, first.text

        res = await library_upload.post(library_upload.body(library_upload.png(12, 12), filename="a.jpg"))

        assert res.status_code == 409, res.text
        assert [put["Key"] for put in library_upload.s3.puts] == ["tenant/instance/a.jpg"]

    async def test_upload_existing_name_with_overwrite_query_param_true_succeeds(self, library_upload) -> None:
        """AC9: overwrite is a query parameter, not a multipart form field.

        The signature assertion pins that contract: an unknown query string is
        ignored by FastAPI, so a 200 here proves nothing on its own.
        """
        import inspect

        assert "overwrite" in inspect.signature(library.upload_file).parameters

        first = await library_upload.post(library_upload.body(library_upload.png(10, 10), filename="a.jpg"))
        assert first.status_code == 200, first.text

        res = await library_upload.post(
            library_upload.body(library_upload.png(12, 12), filename="a.jpg"), query="?overwrite=true"
        )

        assert res.status_code == 200, res.text
        assert [put["Key"] for put in library_upload.s3.puts] == [
            "tenant/instance/a.jpg",
            "tenant/instance/a.jpg",
        ]


def test_max_image_pixels_configured_at_import() -> None:
    """#90: Pillow's global bomb threshold is pinned by utils.images."""
    import publisher_v2.utils.images  # noqa: F401

    assert Image.MAX_IMAGE_PIXELS == 40_000_000
