"""Shared fixtures for web layer tests."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def managed_admin_client(monkeypatch: pytest.MonkeyPatch, env_first_config: None) -> Generator[TestClient, None, None]:
    """TestClient configured for managed storage with admin."""
    monkeypatch.setenv("WEB_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("web_admin_pw", "secret")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
    monkeypatch.setenv("WEB_DEBUG", "true")
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)
    monkeypatch.setenv("CONFIG_SOURCE", "env")

    from publisher_v2.config.source import get_config_source

    get_config_source.cache_clear()

    from publisher_v2.web.app import app

    client = TestClient(app)
    yield client

    get_config_source.cache_clear()


# --- #136: real-app upload harness (real app, real ManagedStorage; boto3 S3 client faked) ---

UPLOAD_BOUNDARY = "pv2boundary"
UPLOAD_CHUNK = 64 * 1024


class _FakeS3:
    def __init__(self) -> None:
        self.puts: list[dict] = []

    def put_object(self, **kwargs):  # type: ignore[no-untyped-def]
        self.puts.append(kwargs)  # Body kept as sent (bytes or a zero-copy file object)
        return {}

    def body(self, index: int = 0) -> bytes:
        """The bytes of put number ``index`` (reads a file-like Body the way botocore would)."""
        body = self.puts[index]["Body"]
        if hasattr(body, "read"):
            body.seek(0)
            return body.read()
        return bytes(body)

    def head_object(self, **kwargs):  # type: ignore[no-untyped-def]
        return {"ContentLength": len(self.body(-1)) if self.puts else 0}


class CountingUploadBody:
    """Multipart body streamed in UPLOAD_CHUNK pieces; records how many bytes the app pulled."""

    def __init__(self, payload: bytes, filename: str = "img.png", pad_to: int = 0) -> None:
        head = (
            f'--{UPLOAD_BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode()
        tail = f"\r\n--{UPLOAD_BOUNDARY}--\r\n".encode()
        self.data = head + payload + (b"\0" * max(0, pad_to - len(payload))) + tail
        self.pulled = 0

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        for i in range(0, len(self.data), UPLOAD_CHUNK):
            piece = self.data[i : i + UPLOAD_CHUNK]
            self.pulled += len(piece)
            yield piece


class _UploadHarness:
    def __init__(self, s3: _FakeS3) -> None:
        self.s3 = s3

    @staticmethod
    def png(width: int, height: int, noise: bool = False, mode: str = "RGB") -> bytes:
        import io
        import os

        from PIL import Image

        buf = io.BytesIO()
        if noise:
            img = Image.frombytes("RGB", (width, height), os.urandom(width * height * 3))
        else:
            img = Image.new(mode, (width, height), 200 if mode == "L" else (200, 100, 50))
        img.save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def body(payload: bytes, filename: str = "img.png", pad_to: int = 0) -> CountingUploadBody:
        return CountingUploadBody(payload, filename=filename, pad_to=pad_to)

    async def post(  # type: ignore[no-untyped-def]
        self, body, *, admin: bool = True, cookie: str | None = None, headers: dict[str, str] | None = None
    ):
        import httpx

        from publisher_v2.web.app import app
        from publisher_v2.web.auth import ADMIN_COOKIE_NAME, mint_admin_cookie_value

        if cookie is None and admin:
            cookie = mint_admin_cookie_value(host="testserver")
        cookies = {ADMIN_COOKIE_NAME: cookie} if cookie else {"other": "1"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver", cookies=cookies
        ) as client:
            return await client.post(
                "/api/library/upload",
                content=body,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={UPLOAD_BOUNDARY}",
                    "X-Requested-With": "XMLHttpRequest",
                    **(headers or {}),
                },
            )


@pytest.fixture
def library_upload(monkeypatch: pytest.MonkeyPatch) -> Generator[_UploadHarness, None, None]:
    """Real app + env-first managed storage with a 2 MB upload cap; boto3 client faked."""
    fake = _FakeS3()
    env = {
        "CONFIG_SOURCE": "env",
        "STORAGE_PROVIDER": "managed",
        "R2_ACCESS_KEY_ID": "ak",
        "R2_SECRET_ACCESS_KEY": "sk",
        "R2_ENDPOINT_URL": "https://r2.example",
        "R2_BUCKET_NAME": "bucket",
        "STORAGE_PATHS": '{"root": "/tenant/instance"}',
        "PUBLISHERS": "[]",
        "OPENAI_SETTINGS": "{}",
        "OPENAI_API_KEY": "sk-test",
        "WEB_SESSION_SECRET": "test-secret",
        "WEB_SECURE_COOKIES": "false",
        "AUTH0_DOMAIN": "test.auth0.com",
        "AUTH0_CLIENT_ID": "cid",
        "AUTH0_CLIENT_SECRET": "cs",
        "LIBRARY_MAX_UPLOAD_MB": "2",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)
    monkeypatch.setattr("publisher_v2.services.managed_storage.boto3.client", lambda *a, **k: fake)
    from publisher_v2.config.source import get_config_source
    from publisher_v2.web.dependencies import get_service
    from publisher_v2.web.routers import library

    get_config_source.cache_clear()
    get_service.cache_clear()
    library._upload_rate_limit.clear()
    yield _UploadHarness(fake)
    get_config_source.cache_clear()
    get_service.cache_clear()
    library._upload_rate_limit.clear()
