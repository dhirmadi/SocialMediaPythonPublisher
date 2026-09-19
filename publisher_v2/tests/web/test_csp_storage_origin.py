"""#144 item 1: the CSP must name the storage origin, not blanket https:.

`img-src ... https:` and `connect-src 'self' https:` were added so the Full Size
control could fetch a presigned URL. They also permit exfiltration of anything
the page can read to any https origin. The policy now carries the configured
storage host and falls back to 'self' when none is known.

Served through the real `publisher_v2.web.app.app` with the real env-first
config loader; only the Dropbox SDK is faked.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

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
    # Re-prime the standalone singleton while this fixture's env is still set:
    # sibling web tests rely on a service being cached and do not set the config
    # env vars themselves, so leaving the cache empty would break them.
    with contextlib.suppress(Exception):
        get_service()


def _has_blanket_https(csp: str) -> bool:
    """True when any directive still carries the bare ``https:`` source."""
    return any(token == "https:" for directive in csp.split(";") for token in directive.split())


def _csp() -> str:
    """The policy the real app serves, with its lifespan run (as uvicorn does)."""
    from fastapi.testclient import TestClient

    from publisher_v2.web.app import app

    with TestClient(app) as client:
        response = client.get("/")
    return response.headers["Content-Security-Policy"]


def test_managed_storage_origin_replaces_blanket_https(managed_app: None) -> None:
    csp = _csp()

    assert "accountid.r2.cloudflarestorage.com" in csp
    assert not _has_blanket_https(csp), csp


def test_dropbox_content_host_is_allowed_not_all_of_https(dropbox_app: None) -> None:
    csp = _csp()

    assert "dropboxusercontent.com" in csp
    assert not _has_blanket_https(csp), csp


@pytest.mark.parametrize(
    "hostile_endpoint",
    [
        "https://evil.example; script-src *",
        "https://evil.example *",
        "https://evil.example\tfoo",
    ],
)
def test_hostile_endpoint_cannot_inject_a_directive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, hostile_endpoint: str
) -> None:
    """An endpoint_url is tenant-influenced (BYOK) — it must never reach the header raw."""
    env = _base_env(tmp_path) | {
        "STORAGE_PROVIDER": "managed",
        "R2_ACCESS_KEY_ID": "k",
        "R2_SECRET_ACCESS_KEY": "s",
        "R2_ENDPOINT_URL": hostile_endpoint,
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
        csp = _csp()
    get_config_source.cache_clear()
    get_service.cache_clear()
    with contextlib.suppress(Exception):
        get_service()

    # One script-src — the nonce one — and no extra source smuggled into any
    # directive. A host that urlparse folds into a single valid netloc may still
    # appear; what must never happen is a second source or a second directive.
    assert csp.count("script-src") == 1, csp
    assert "*" not in csp, csp
    assert not _has_blanket_https(csp), csp
    for directive in csp.split(";"):
        if directive.strip().startswith(("img-src", "connect-src")):
            origins = [t for t in directive.split() if t.startswith("http")]
            assert len(origins) <= 1, csp


def _csp_for_endpoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, endpoint: str) -> str:
    env = _base_env(tmp_path) | {
        "STORAGE_PROVIDER": "managed",
        "R2_ACCESS_KEY_ID": "k",
        "R2_SECRET_ACCESS_KEY": "s",
        "R2_ENDPOINT_URL": endpoint,
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
        csp = _csp()
    get_config_source.cache_clear()
    get_service.cache_clear()
    with contextlib.suppress(Exception):
        get_service()
    return csp


def test_malformed_endpoint_does_not_break_the_request(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """An unparseable endpoint_url must degrade to 'self', not 500 every request."""
    csp = _csp_for_endpoint(monkeypatch, tmp_path, "http://[evil")

    assert "img-src 'self' data: blob:;" in csp, csp
    assert not _has_blanket_https(csp), csp


def test_ipv6_endpoint_is_allowed(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    csp = _csp_for_endpoint(monkeypatch, tmp_path, "https://[2001:db8::1]:9000")

    assert "https://[2001:db8::1]:9000" in csp, csp


def test_policy_keeps_its_other_directives(managed_app: None) -> None:
    csp = _csp()

    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "script-src 'self' 'nonce-" in csp
