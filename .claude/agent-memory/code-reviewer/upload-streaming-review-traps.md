---
name: upload-streaming-review-traps
description: /api/library/upload streaming (#136) traps — botocore bytearray copy, Pillow IDAT, uvicorn post-413 drain, python-multipart finalize() no-op, OpenAPI requestBody loss
metadata:
  type: project
---

Memory/ordering claims for the upload route are only as good as what the harness fakes.
Verified 2026-09-19, re-verified 2026-09-20 on fix/136-upload-gate-before-body (PR #157).

- **botocore copies bytearray bodies**: `convert_body_to_file_like_object` wraps only `bytes`/`str`; a `bytearray` Body reaches `httpchecksum` (`io.BytesIO(body)`) and is copied whole. A seekable file-like Body (`utils/memory_io.reader_over`) avoids it; the residual ~2.5-3 MB is botocore's 1 MiB aws-chunked framing, size-independent. Tests that fake `managed_storage.boto3.client` cannot see the copy — short-circuit a *real* client with a `before-send` event hook instead.
- **Pillow PNG verify**: `ChunkStream.verify` -> `ImageFile._safe_read` joins each chunk whole, so a single-IDAT PNG costs ~3x transiently. Pillow-saved test PNGs hide this.
- **uvicorn (h11)**: after an early 413 without `Connection: close` it keeps the socket open and discards the rest of the body forever. Bandwidth/CPU only; app memory stays bounded.
- **python-multipart `finalize()` is a documented no-op**: a body that just stops mid-part parses as a *complete* upload. Nothing else notices — JPEG `verify()` does not decode, so Pillow passes a truncated file through and a truncated object reaches storage. The fix tracks `on_part_end` for the file part **and** `on_end` for the terminator. A PNG happens to 415 anyway, so a PNG-only test will not catch the hole.
- **Dropping `UploadFile` drops the OpenAPI `requestBody`**: the route's schema loses the multipart body entirely (`app.openapi()['paths'][...]['post']` has no `requestBody`), so /docs and generated clients lose the file field. Restore with `openapi_extra=` on the decorator.
- **Missing/invalid part is now 400, not FastAPI's 422** — an endpoint-contract change worth naming.
- **Envelope accounting `received - len(file_buf) > OVERHEAD + len(chunk)`** degrades to a no-op when the server delivers one large chunk; the real bound is then `max_bytes + OVERHEAD`. Memory is still fine (junk part data is counted, not buffered) — it is a CPU bound, not a memory one.
- **Byte-at-a-time bodies**: through `httpx.ASGITransport` a 2 MB body in 1-byte chunks takes >300 s and exits via the 408 read timeout, never reaching the 413. Harness-dominated (real uvicorn coalesces), but it shows the read timeout is the only wall-clock bound per upload.

**How to apply:** for any upload/body-streaming change, measure with the real boto3 client, try a single-IDAT PNG, truncate the multipart body mid-part, diff `app.openapi()` before/after, and probe 1-byte chunking for boundary straddling.
- **`reader.close()` leaks are invisible under CPython refcounting**: after `put_object` returns, nothing retains the `reader_over()` file, so `IOBase.__del__` closes it and the caller's bytearray is resizable again — verified by probe. `test_put_object_leaves_the_callers_buffer_resizable` only goes red because the test's `before-send` hook does `sent.append(request)` and the request retains the body. Real guard, but its failure signal is harness-held.
- **`tests/web/conftest.py::_FakeS3` consumes the Body inside `put_object`** (botocore-like) and records bodies >256 KiB by size only (`puts[i]["Size"]`, `body()` returns `b""`). A fake that read the Body *after* the call would fail against correct code once the reader is closed. Side effect: the fake's own 256 KiB head read raised the peak-memory test from ~2.11 MB to ~2.29 MB against a ~2.92 MB bound.
