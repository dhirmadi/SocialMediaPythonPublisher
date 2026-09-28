"""Library uploads through the real app: auth, CSRF, rate limit, size cap, image safety, keys.

SEC-6 (#90), #136, PUB-031 AC10/AC11 and PUB-048 (#188) AC8/AC9. Real
``publisher_v2.web.app.app`` over ``httpx.ASGITransport`` (which feeds the
request body to the app chunk by chunk), real env-first config and real
``ManagedStorage``; only boto3's S3 client is faked (``library_upload`` fixture
in tests/web/conftest.py). The request body is an async generator that counts
the bytes the app actually pulled.
"""

from __future__ import annotations

import io
import time
import tracemalloc

import pytest
from PIL import Image

from publisher_v2.web.routers import library

from .conftest import UPLOAD_CHUNK

CAP = 2 * 1024 * 1024  # LIBRARY_MAX_UPLOAD_MB=2 in the fixture


def _image_bytes(fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 100, 50)).save(buf, format=fmt)
    return buf.getvalue()


async def test_unauthenticated_upload_reads_no_body(library_upload) -> None:
    body = library_upload.body(library_upload.png(10, 10), pad_to=1024 * 1024)
    res = await library_upload.post(body, admin=False)
    assert res.status_code in (401, 403)
    assert body.pulled == 0
    assert library_upload.s3.puts == []


async def test_rate_limited_upload_reads_no_body(library_upload) -> None:
    from publisher_v2.web.auth import mint_admin_cookie_value

    cookie = mint_admin_cookie_value(host="testserver")
    # The admin cookie value is the rate-limit key; fill its window.
    library._upload_rate_limit[cookie] = [time.time()] * library._RATE_LIMIT_MAX
    body = library_upload.body(library_upload.png(10, 10), pad_to=1024 * 1024)
    res = await library_upload.post(body, cookie=cookie)
    assert res.status_code == 429
    assert body.pulled == 0


async def test_over_cap_body_cut_off_mid_stream(library_upload) -> None:
    body = library_upload.body(library_upload.png(10, 10), pad_to=CAP + 1 + 4 * 1024 * 1024)
    res = await library_upload.post(body)
    assert res.status_code == 413
    assert body.pulled < len(body.data), "the rest of the stream must not be consumed"
    assert body.pulled <= CAP + 2 * UPLOAD_CHUNK + 1024
    assert library_upload.s3.puts == []


async def test_one_byte_over_cap_is_rejected(library_upload) -> None:
    res = await library_upload.post(library_upload.body(library_upload.png(10, 10), pad_to=CAP + 1))
    assert res.status_code == 413


async def test_jpeg_upload_succeeds(library_upload) -> None:
    """PUB-031 AC10: JPEG is the other allowed format (the PNG case is test_valid_image_uploads)."""
    payload = _image_bytes("JPEG")
    res = await library_upload.post(library_upload.body(payload, filename="test.jpg"))
    assert res.status_code == 200, res.text
    assert res.json()["key"] == "tenant/instance/test.jpg"
    assert library_upload.s3.body(0) == payload


async def test_upload_rate_limit_429_after_ten_uploads(library_upload) -> None:
    """PUB-031 AC11: ten uploads per admin session per minute; the eleventh is refused unread."""
    from publisher_v2.web.auth import mint_admin_cookie_value

    cookie = mint_admin_cookie_value(host="testserver")
    for i in range(library._RATE_LIMIT_MAX):
        body = library_upload.body(library_upload.png(4, 4), filename=f"img{i}.png")
        res = await library_upload.post(body, cookie=cookie)
        assert res.status_code == 200, f"upload {i}: {res.text}"

    body = library_upload.body(library_upload.png(4, 4), filename="img11.png")
    res = await library_upload.post(body, cookie=cookie)

    assert res.status_code == 429
    assert body.pulled == 0
    assert len(library_upload.s3.puts) == library._RATE_LIMIT_MAX


async def test_upload_cookie_only_without_xrw_is_csrf_blocked(library_upload) -> None:
    """Browser uploads ride the admin cookie, so the CSRF middleware requires X-Requested-With."""
    res = await library_upload.post(
        library_upload.body(library_upload.png(4, 4), filename="test.png"), headers={"X-Requested-With": ""}
    )
    assert res.status_code == 403
    assert res.json()["detail"] == "CSRF check failed"
    assert library_upload.s3.puts == []


async def test_valid_image_uploads(library_upload) -> None:
    payload = library_upload.png(40, 30)
    res = await library_upload.post(library_upload.body(payload, filename="ok.png"))
    assert res.status_code == 200, res.text
    assert res.json()["key"] == "tenant/instance/ok.png"
    assert library_upload.s3.body(0) == payload
    assert library_upload.s3.puts[0]["ContentType"] == "image/png"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b"not an image at all", id="not-an-image"),
        # Sec H-3: the client's Content-Type is not trusted — the magic bytes decide.
        pytest.param(b"<script>alert(1)</script>", id="script-sent-as-image"),
        pytest.param(_image_bytes("GIF"), id="real-gif-not-an-allowed-format"),
    ],
)
async def test_non_image_still_415(library_upload, payload: bytes) -> None:
    res = await library_upload.post(library_upload.body(payload, filename="x.png"))
    assert res.status_code == 415
    assert library_upload.s3.puts == []


async def test_peak_memory_bounded_by_cap_plus_a_chunk(library_upload) -> None:
    payload = library_upload.png(760, 760, noise=True)  # ~1.7 MB of incompressible PNG, under the 2 MB cap
    body = library_upload.body(payload, filename="big.png")
    # Warm up (imports, app startup, Pillow plugins) so only the upload is measured.
    warm = await library_upload.post(library_upload.body(library_upload.png(8, 8), filename="warm.png"))
    assert warm.status_code == 200, warm.text
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        res = await library_upload.post(body)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert res.status_code == 200, res.text
    # The file is held once plus one chunk; a second full copy would exceed this.
    # Generous slack for Pillow/httpx/framework overhead.
    assert peak < len(payload) + 2 * UPLOAD_CHUNK + 1024 * 1024, peak


async def test_malformed_multipart_is_400_not_500(library_upload) -> None:
    body = library_upload.body(b"", filename="x.png")
    body.data = b"garbage before any boundary\r\n" + body.data.replace(b"Content-Disposition", b"Content Disposition")
    res = await library_upload.post(body)
    assert res.status_code == 400, res.text


async def test_oversized_part_header_rejected_fast(library_upload) -> None:
    from .conftest import UPLOAD_BOUNDARY

    body = library_upload.body(b"")
    huge = b"X-Pad: " + b"a" * (64 * 1024) + b"\r\n"
    head = f'--{UPLOAD_BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="a.png"\r\n'.encode()
    body.data = head + huge + b"\r\n" + library_upload.png(4, 4) + f"\r\n--{UPLOAD_BOUNDARY}--\r\n".encode()
    res = await library_upload.post(body)
    # 400 from our own _MAX_PART_HEADER_BYTES guard (not python-multipart): the
    # part header blows the 8 KiB budget before any file data is seen, so the
    # 413 file cap is never consulted.
    assert res.status_code == 400, res.text
    assert body.pulled < len(body.data)


async def test_slow_body_times_out_with_408(library_upload, monkeypatch) -> None:
    import asyncio

    monkeypatch.setattr(library, "_UPLOAD_READ_TIMEOUT_SECONDS", 0.2)

    class _Slow:
        pulled = 0

        async def __aiter__(self):  # type: ignore[no-untyped-def]
            from .conftest import UPLOAD_BOUNDARY

            yield f'--{UPLOAD_BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="a.png"\r\n\r\n'.encode()
            await asyncio.sleep(5)
            yield b"never"

    res = await library_upload.post(_Slow())
    assert res.status_code == 408


async def test_client_disconnect_mid_upload_is_not_a_500(library_upload) -> None:
    """Raw ASGI through the real app: the client goes away after the first chunk."""
    from publisher_v2.web.app import app
    from publisher_v2.web.auth import ADMIN_COOKIE_NAME, mint_admin_cookie_value

    from .conftest import UPLOAD_BOUNDARY

    cookie = mint_admin_cookie_value(host="testserver")
    first = f'--{UPLOAD_BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="a.png"\r\n\r\n'.encode()
    messages = iter(
        [
            {"type": "http.request", "body": first, "more_body": True},
            {"type": "http.disconnect"},
        ]
    )
    sent: list[dict] = []

    async def receive():  # type: ignore[no-untyped-def]
        return next(messages)

    async def send(message):  # type: ignore[no-untyped-def]
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/library/upload",
        "raw_path": b"/api/library/upload",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", f"multipart/form-data; boundary={UPLOAD_BOUNDARY}".encode()),
            (b"x-requested-with", b"XMLHttpRequest"),
            (b"cookie", f"{ADMIN_COOKIE_NAME}={cookie}".encode()),
        ],
        "client": ("127.0.0.1", 5000),
        "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    starts = [m for m in sent if m["type"] == "http.response.start"]
    assert starts and starts[0]["status"] == 400


async def test_non_multipart_request_is_400(library_upload) -> None:
    body = library_upload.body(b"x")
    res = await library_upload.post(body, headers={"Content-Type": "application/octet-stream"})
    assert res.status_code == 400
    assert body.pulled == 0


async def test_missing_file_part_is_400(library_upload) -> None:
    from .conftest import UPLOAD_BOUNDARY

    body = library_upload.body(b"")
    body.data = (
        f'--{UPLOAD_BOUNDARY}\r\nContent-Disposition: form-data; name="other"\r\n\r\nhello\r\n--{UPLOAD_BOUNDARY}--\r\n'
    ).encode()
    res = await library_upload.post(body)
    assert res.status_code == 400
    assert library_upload.s3.puts == []


async def test_unparseable_content_length_falls_back_to_the_stream_cap(library_upload) -> None:
    payload = library_upload.png(12, 12)
    res = await library_upload.post(library_upload.body(payload, filename="c.png"), headers={"Content-Length": "abc"})
    # The unparseable header is ignored (the int() raises, the pre-check is
    # skipped) and the stream cap admits this small payload, so the upload
    # succeeds. What must not happen is a 500 or a bypass of the cap.
    assert res.status_code == 200, res.text


async def test_bytes_outside_the_file_part_are_capped(library_upload) -> None:
    """Many junk parts / whitespace outside the file part: rejected at the 16 KiB envelope, not the 2 MB cap."""
    from .conftest import UPLOAD_BOUNDARY

    junk = b"".join(
        f'--{UPLOAD_BOUNDARY}\r\nContent-Disposition: form-data; name="p{i}"\r\n\r\nx\r\n'.encode()
        for i in range(20_000)
    )
    body = library_upload.body(b"")
    body.data = junk + f"--{UPLOAD_BOUNDARY}--\r\n".encode()
    res = await library_upload.post(body)
    # 400: the envelope cap is hit while parsing non-file parts, which surfaces
    # as a malformed-request error rather than the file-size 413.
    assert res.status_code == 400, res.text
    assert body.pulled <= 16 * 1024 + 2 * 64 * 1024


async def test_a_truncated_body_is_rejected_not_stored(library_upload) -> None:
    """python-multipart's finalize() is a no-op, so nothing else notices a body that just stops.

    A client that dies mid-upload — or lies about Content-Length — otherwise
    parses as a complete part and stores a truncated object: JPEG verify()
    does not decode, so Pillow passes it through.
    """
    from .conftest import UPLOAD_BOUNDARY

    payload = library_upload.png(40, 30)
    body = library_upload.body(payload)
    body.data = body.data[: -len(f"\r\n--{UPLOAD_BOUNDARY}--\r\n") - 40]

    res = await library_upload.post(body)

    assert res.status_code == 400, res.text
    assert "Incomplete" in res.text
    assert library_upload.s3.puts == [], "a truncated object must never reach storage"


async def test_a_complete_body_is_not_mistaken_for_a_truncated_one(library_upload) -> None:
    res = await library_upload.post(library_upload.body(library_upload.png(8, 8), filename="whole.png"))

    assert res.status_code == 200, res.text


async def test_a_traversal_filename_cannot_escape_the_image_folder(library_upload) -> None:
    """The filename's provenance changed here: hand-parsed Content-Disposition, not UploadFile."""
    res = await library_upload.post(library_upload.body(library_upload.png(8, 8), filename="../../etc/passwd.png"))

    assert res.status_code == 200, res.text
    assert res.json()["key"] == "tenant/instance/passwd.png"
    assert library_upload.s3.puts[0]["Key"] == "tenant/instance/passwd.png"


async def test_an_rfc2231_encoded_traversal_filename_is_sanitized_too(library_upload) -> None:
    """An RFC 2231-encoded traversal filename cannot escape the image folder.

    python-multipart >= 0.0.27 ignores the RFC 5987/2231 `filename*` parameter
    outright -- RFC 7578 section 4.2 forbids it in `multipart/form-data`, and it
    was removed as part of the header-parsing fixes (PYSEC-2026-3036/3037/3039/
    3040) this repo pulled in. So the hostile bytes never reach
    `_sanitize_filename` at all and the default name is used, which is a
    stricter guarantee than decoding them and then stripping the path. The
    assertion below changed with that upgrade; the property under test did not.
    """
    from .conftest import UPLOAD_BOUNDARY

    payload = library_upload.png(8, 8)
    body = library_upload.body(payload)
    head = (
        f"--{UPLOAD_BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="file"; '
        "filename*=UTF-8''%2e%2e%2f%2e%2e%2fevil.png\r\n"
        "Content-Type: image/png\r\n\r\n"
    ).encode()
    body.data = head + payload + f"\r\n--{UPLOAD_BOUNDARY}--\r\n".encode()

    res = await library_upload.post(body)

    assert res.status_code == 200, res.text
    assert res.json()["key"] == "tenant/instance/upload.jpg"
    # Pin the security property itself, so this cannot pass for the wrong reason:
    # nothing attacker-controlled reaches the key, and it stays under the prefix.
    assert "evil" not in res.json()["key"]
    assert library_upload.s3.puts[0]["Key"] == "tenant/instance/upload.jpg"


async def test_a_body_cut_before_the_terminator_is_rejected(library_upload) -> None:
    """The file part closes cleanly, but the body stops before `--boundary--`.

    This is the half of the completeness check that `file_part_ended` alone
    does not cover: the part ended, the body did not.
    """
    from .conftest import UPLOAD_BOUNDARY

    payload = library_upload.png(16, 16)
    body = library_upload.body(payload)
    terminator = f"--{UPLOAD_BOUNDARY}--\r\n".encode()
    assert body.data.endswith(terminator)
    # The file part's closing boundary is kept (so on_part_end fires); only the
    # trailing "--" that ends the body is missing.
    body.data = body.data[: -len(terminator)] + f"--{UPLOAD_BOUNDARY}\r\n".encode()

    res = await library_upload.post(body)

    assert res.status_code == 400, res.text
    assert "Incomplete" in res.text
    assert library_upload.s3.puts == []


def test_the_upload_endpoint_still_documents_its_multipart_body() -> None:
    """Dropping the UploadFile parameter is what stops FastAPI parsing the body — and
    it also drops the requestBody from the schema unless it is declared by hand."""
    from publisher_v2.web.app import app

    operation = app.openapi()["paths"]["/api/library/upload"]["post"]

    assert operation["requestBody"]["required"] is True
    schema = operation["requestBody"]["content"]["multipart/form-data"]["schema"]
    assert schema["properties"]["file"] == {"type": "string", "format": "binary"}
    assert schema["required"] == ["file"]


class TestBoundedBuffering:
    async def test_content_length_over_cap_rejected_before_any_read(self, library_upload) -> None:
        body = library_upload.body(library_upload.png(10, 10))
        res = await library_upload.post(body, headers={"Content-Length": str(3 * CAP)})
        assert res.status_code == 413
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
