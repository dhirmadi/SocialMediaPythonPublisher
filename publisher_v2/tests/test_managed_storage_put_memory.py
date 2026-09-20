"""#136: ManagedStorage.put_object must not copy a bytearray upload inside botocore.

Real ``boto3`` S3 client; only the HTTP send is short-circuited by a
``before-send`` event hook (the network boundary). botocore wraps a
``bytearray`` Body in ``io.BytesIO`` for checksums, which copies it.
"""

from __future__ import annotations

import os
import tracemalloc

from botocore.awsrequest import AWSResponse

from publisher_v2.config.schema import ManagedStorageConfig
from publisher_v2.services.managed_storage import ManagedStorage


class _Raw:
    def stream(self, **_kwargs):  # type: ignore[no-untyped-def]
        yield b""


def _storage_with_capture() -> tuple[ManagedStorage, list]:
    storage = ManagedStorage(
        ManagedStorageConfig(
            access_key_id="ak",
            secret_access_key="sk",
            endpoint_url="https://r2.example",
            bucket="bucket",
        )
    )
    sent: list = []

    def _before_send(request, **_kwargs):  # type: ignore[no-untyped-def]
        sent.append(request)
        body = request.body
        if hasattr(body, "read"):
            while body.read(1024 * 1024):  # stream it like the HTTP layer would
                pass
        return AWSResponse(request.url, 200, {}, _Raw())

    storage.client.meta.events.register("before-send.s3.PutObject", _before_send)
    return storage, sent


async def test_put_object_bytearray_is_not_copied() -> None:
    storage, sent = _storage_with_capture()
    data = bytearray(os.urandom(8 * 1024 * 1024))
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        base, _ = tracemalloc.get_traced_memory()
        await storage.put_object("k/big.png", data, "image/png")
        _cur, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(sent) == 1
    assert peak - base < len(data) // 2, f"put_object copied the upload: +{(peak - base) / 1e6:.1f} MB"


async def test_put_object_sends_the_exact_bytes() -> None:
    storage, sent = _storage_with_capture()
    data = bytearray(b"\x89PNG" + os.urandom(300_000))
    captured: list[bytes] = []

    def _grab(request, **_kwargs):  # type: ignore[no-untyped-def]
        body = request.body
        if hasattr(body, "seek"):
            body.seek(0)
        captured.append(body.read() if hasattr(body, "read") else bytes(body))
        return AWSResponse(request.url, 200, {}, _Raw())

    storage.client.meta.events.register_first("before-send.s3.PutObject", _grab)
    await storage.put_object("k/x.png", data, "image/png")
    # botocore may frame the body (aws-chunked + trailing checksum); the payload must be intact inside it.
    assert len(captured) == 1 and bytes(data) in captured[0]


async def test_put_object_leaves_the_callers_buffer_resizable() -> None:
    """The zero-copy body exports a memoryview; an un-released one pins the caller's buffer.

    A pinned bytearray raises BufferError on the next ``extend()`` — far from
    the put that caused it — so the reader is closed when the call returns.
    """
    storage, sent = _storage_with_capture()
    data = bytearray(b"\x89PNG" + os.urandom(1000))

    await storage.put_object("k/x.png", data, "image/png")

    assert len(sent) == 1
    data.extend(b"tail")  # BufferError here means the reader was left open
    assert bytes(data).endswith(b"tail")
