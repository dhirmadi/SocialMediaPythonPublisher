"""#144 item 1: the CSP must name the storage origin, not blanket https:.

`img-src ... https:` and `connect-src 'self' https:` were added so the Full Size
control could fetch a presigned URL. They also permit exfiltration of anything
the page can read to any https origin. The policy now carries the configured
storage host and falls back to 'self' when none is known.

Served through the real `publisher_v2.web.app.app` with the real env-first
config loader; only the Dropbox SDK is faked.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import httpx
import pytest

R2_ENDPOINT = "https://accountid.r2.cloudflarestorage.com"


def _base_env(tmp_path: Any) -> dict[str, str]:
    return {
        "CONFIG_SOURCE": "env",
        "HOME": str(tmp_path),
        "STORAGE_PATHS": json.dumps({"root": "/Photos", "archive": "archive"}),
        "PUBLISHERS": json.dumps([{"type": "telegram", "channel_id": "@chan"}]),
        "TELEGRAM_BOT_TOKEN": "tg",
        "OPENAI_SETTINGS": "{}",
        "OPENAI_API_KEY": "sk-test",
        "WEB_SESSION_SECRET": "test-secret",
        "WEB_SECURE_COOKIES": "false",
    }


@pytest.fixture
def managed_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[None]:
    env = _base_env(tmp_path) | {
        "STORAGE_PROVIDER": "managed",
        "R2_ACCESS_KEY_ID": "k",
        "R2_SECRET_ACCESS_KEY": "s",
        "R2_ENDPOINT_URL": R2_ENDPOINT,
        "R2_BUCKET_NAME": "bucket",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for key in ("ORCHESTRATOR_BASE_URL", "DATABASE_URL", "CONFIG_PATH"):
        monkeypatch.delenv(key, raising=False)
    from publisher_v2.config.source import get_config_source
    from publisher_v2.web.app import get_service

    get_config_source.cache_clear()
    get_service.cache_clear()
    with patch("publisher_v2.services.managed_storage.boto3"):
        yield
    get_config_source.cache_clear()
    get_service.cache_clear()


@pytest.fixture
def dropbox_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[None]:
    env = _base_env(tmp_path) | {
        "STORAGE_PROVIDER": "dropbox",
        "DROPBOX_APP_KEY": "k",
        "DROPBOX_APP_SECRET": "s",
        "DROPBOX_REFRESH_TOKEN": "r",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for key in ("ORCHESTRATOR_BASE_URL", "DATABASE_URL", "CONFIG_PATH"):
        monkeypatch.delenv(key, raising=False)
    from publisher_v2.config.source import get_config_source
    from publisher_v2.web.app import get_service

    get_config_source.cache_clear()
    get_service.cache_clear()
    with patch("publisher_v2.services.storage.dropbox.Dropbox"):
        yield
    get_config_source.cache_clear()
    get_service.cache_clear()


def _has_blanket_https(csp: str) -> bool:
    """True when any directive still carries the bare ``https:`` source."""
    return any(token == "https:" for directive in csp.split(";") for token in directive.split())


async def _csp() -> str:
    from publisher_v2.web.app import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")
    return response.headers["Content-Security-Policy"]


async def test_managed_storage_origin_replaces_blanket_https(managed_app: None) -> None:
    csp = await _csp()

    assert "accountid.r2.cloudflarestorage.com" in csp
    assert not _has_blanket_https(csp), csp


async def test_dropbox_content_host_is_allowed_not_all_of_https(dropbox_app: None) -> None:
    csp = await _csp()

    assert "dropboxusercontent.com" in csp
    assert not _has_blanket_https(csp), csp


async def test_policy_keeps_its_other_directives(managed_app: None) -> None:
    csp = await _csp()

    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "script-src 'self' 'nonce-" in csp
