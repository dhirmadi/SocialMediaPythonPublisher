"""#136: the upload body must not be read before auth, rate limit and the size cap.

Real ``publisher_v2.web.app.app`` over ``httpx.ASGITransport`` (which feeds the
request body to the app chunk by chunk), real env-first config and real
``ManagedStorage``; only boto3's S3 client is faked (``library_upload`` fixture
in tests/web/conftest.py). The request body is an async generator that counts
the bytes the app actually pulled.
"""

from __future__ import annotations

import time
import tracemalloc

from .conftest import UPLOAD_CHUNK

CAP = 2 * 1024 * 1024


async def test_unauthenticated_upload_reads_no_body(library_upload) -> None:
    body = library_upload.body(library_upload.png(10, 10), pad_to=1024 * 1024)
    res = await library_upload.post(body, admin=False)
    assert res.status_code in (401, 403)
    assert body.pulled == 0
    assert library_upload.s3.puts == []


async def test_rate_limited_upload_reads_no_body(library_upload) -> None:
    from publisher_v2.web.auth import mint_admin_cookie_value
    from publisher_v2.web.routers import library

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


async def test_valid_image_uploads(library_upload) -> None:
    payload = library_upload.png(40, 30)
    res = await library_upload.post(library_upload.body(payload, filename="ok.png"))
    assert res.status_code == 200, res.text
    assert res.json()["key"] == "tenant/instance/ok.png"
    assert library_upload.s3.body(0) == payload
    assert library_upload.s3.puts[0]["ContentType"] == "image/png"


async def test_non_image_still_415(library_upload) -> None:
    res = await library_upload.post(library_upload.body(b"not an image at all", filename="x.png"))
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
    assert res.status_code in (400, 413), res.text
    assert body.pulled < len(body.data)


async def test_slow_body_times_out_with_408(library_upload, monkeypatch) -> None:
    import asyncio

    from publisher_v2.web.routers import library

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
    # httpx may refuse to send a non-numeric header; either way no 500 and no bypass.
    assert res.status_code in (200, 400), res.text


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
    assert res.status_code in (400, 413), res.text
    assert body.pulled <= 16 * 1024 + 2 * 64 * 1024
