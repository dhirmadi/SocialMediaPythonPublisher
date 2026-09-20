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
    # Re-prime the standalone singleton while this fixture's env is still set.
    # tests/web/test_web_settings_voice_profile.py builds no service of its own and reuses whatever the
    # get_service lru_cache happens to hold; clearing it without re-priming fails
    # 6 tests there with "required env vars not set". Pre-existing isolation debt,
    # not introduced here — noted as a follow-up on #128.
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


class TestPerTenantOrigins:
    """#144: in orchestrated mode the policy must come from the request's own tenant config.

    This is the branch the standalone tests never reach: there the origin comes
    from the startup snapshot on app.state.
    """

    @staticmethod
    def _config(endpoint: str | None):
        from publisher_v2.config.schema import (
            ApplicationConfig,
            ContentConfig,
            DropboxConfig,
            ManagedStorageConfig,
            OpenAIConfig,
            PlatformsConfig,
            StoragePathConfig,
        )

        common = {
            "storage_paths": StoragePathConfig(image_folder="/Photos"),
            "openai": OpenAIConfig(api_key="sk-test"),
            "platforms": PlatformsConfig(),
            "content": ContentConfig(hashtag_string="", archive=True, debug=False),
        }
        if endpoint is None:
            return ApplicationConfig(
                dropbox=DropboxConfig(
                    app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
                ),
                **common,
            )
        return ApplicationConfig(
            managed=ManagedStorageConfig(
                access_key_id="k", secret_access_key="s", endpoint_url=endpoint, bucket="b", region="auto"
            ),
            **common,
        )

    def test_each_tenant_gets_its_own_storage_origin(self) -> None:
        from publisher_v2.web.middleware_security import storage_origins_for_config

        tenant_a = self._config("https://a-account.r2.cloudflarestorage.com")
        tenant_b = self._config("https://b-account.r2.cloudflarestorage.com")
        tenant_dropbox = self._config(None)

        assert storage_origins_for_config(tenant_a) == ["https://a-account.r2.cloudflarestorage.com"]
        assert storage_origins_for_config(tenant_b) == ["https://b-account.r2.cloudflarestorage.com"]
        assert storage_origins_for_config(tenant_dropbox) == ["https://*.dropboxusercontent.com"]

    def test_the_request_scoped_config_wins_over_the_startup_snapshot(self) -> None:
        """A tenant's config must never be overridden by the instance-level value."""
        from types import SimpleNamespace

        from publisher_v2.web.middleware_security import _storage_origins

        request = SimpleNamespace(
            state=SimpleNamespace(config=self._config("https://tenant.r2.cloudflarestorage.com")),
            app=SimpleNamespace(state=SimpleNamespace(csp_storage_origins=["https://instance.example"])),
        )

        assert _storage_origins(request) == ["https://tenant.r2.cloudflarestorage.com"]

    def test_a_tenant_with_no_resolvable_storage_gets_nothing_extra(self) -> None:
        from types import SimpleNamespace

        from publisher_v2.web.middleware_security import _storage_origins

        request = SimpleNamespace(
            state=SimpleNamespace(config=None, web_service=SimpleNamespace(config=None)),
            app=SimpleNamespace(state=SimpleNamespace(csp_storage_origins=[])),
        )

        assert _storage_origins(request) == []
