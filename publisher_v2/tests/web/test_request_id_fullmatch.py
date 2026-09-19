"""#144 item 7: the request-id filter used re.match with a trailing $.

``$`` also matches just before a final newline, so "abc\n" passed the pattern
and a newline reached the correlation id — and every log line built from it.
Exercised through the real app's middleware, not the compiled pattern.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import dropbox
import httpx
import pytest
from PIL import Image


class _FakeDropbox:
    """Minimal stand-in for the Dropbox SDK client: one image in the folder."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        import hashlib
        import io

        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="JPEG")
        self._bytes = buf.getvalue()
        self._hash = hashlib.sha256(self._bytes).hexdigest()

    def files_list_folder(self, path: str) -> Any:
        from types import SimpleNamespace

        entry = dropbox.files.FileMetadata(
            name="img.jpg", path_lower=f"{path}/img.jpg".lower(), content_hash=self._hash
        )
        return SimpleNamespace(entries=[entry], has_more=False, cursor=None)

    def files_download(self, path: str) -> tuple[None, Any]:
        from types import SimpleNamespace

        return None, SimpleNamespace(content=self._bytes)

    def files_get_temporary_link(self, path: str) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(link=f"https://dl.dropboxusercontent.com{path}")

    def files_get_metadata(self, path: str) -> Any:
        return dropbox.files.FileMetadata(name="img.jpg", id="id:1", rev="0123456789", size=len(self._bytes))


@pytest.fixture
def real_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[None]:
    env = {
        "CONFIG_SOURCE": "env",
        "HOME": str(tmp_path),
        "STORAGE_PATHS": json.dumps({"root": "/Photos", "archive": "archive"}),
        "PUBLISHERS": json.dumps([{"type": "telegram", "channel_id": "@chan"}]),
        "TELEGRAM_BOT_TOKEN": "tg",
        "OPENAI_SETTINGS": "{}",
        "OPENAI_API_KEY": "sk-test",
        "DROPBOX_APP_KEY": "k",
        "DROPBOX_APP_SECRET": "s",
        "DROPBOX_REFRESH_TOKEN": "r",
        "WEB_SESSION_SECRET": "test-secret",
        "WEB_SECURE_COOKIES": "false",
        "AUTH0_DOMAIN": "test.auth0.com",
        "AUTH0_CLIENT_ID": "cid",
        "AUTH0_CLIENT_SECRET": "csecret",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for key in ("ORCHESTRATOR_BASE_URL", "DATABASE_URL", "CONFIG_PATH"):
        monkeypatch.delenv(key, raising=False)
    from publisher_v2.config.source import get_config_source
    from publisher_v2.web.app import get_service

    get_config_source.cache_clear()
    get_service.cache_clear()
    with patch("publisher_v2.services.storage.dropbox.Dropbox", _FakeDropbox):
        yield
    get_config_source.cache_clear()
    get_service.cache_clear()
    # Re-prime the standalone singleton while this fixture's env is still set:
    # sibling web tests rely on a service being cached and do not set the config
    # env vars themselves, so leaving the cache empty would break them.
    with contextlib.suppress(Exception):
        get_service()


async def _correlation_id(header: str) -> str:
    """The id the real app echoes back on a request carrying this X-Request-ID."""
    from publisher_v2.web.app import app
    from publisher_v2.web.auth import ADMIN_COOKIE_NAME, mint_admin_cookie_value

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={ADMIN_COOKIE_NAME: mint_admin_cookie_value(host="testserver")},
    ) as client:
        response = await client.get("/api/images/img.jpg", headers={"X-Request-ID": header})
    assert response.status_code == 200, (response.status_code, response.text[:200])
    return response.headers["X-Correlation-ID"]


async def test_trailing_newline_is_rejected(real_app: None) -> None:
    returned = await _correlation_id("abc123\n")

    assert returned != "abc123\n"
    assert "\n" not in returned


async def test_clean_request_id_is_still_honoured(real_app: None) -> None:
    assert await _correlation_id("abc123") == "abc123"
