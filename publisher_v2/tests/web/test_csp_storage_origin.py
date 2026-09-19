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
import logging
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
        # A comma is preserved by urlparse (a tab is stripped, so that vector
        # could not tell a permissive regex from a strict one).
        "https://evil.example,other.example",
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
    # A comma would split the header into two whole policies, so it must never
    # survive into a source either.
    assert "," not in csp, csp
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


def test_ipv6_endpoint_is_not_emitted(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """CSP's host-source grammar has no IPv6 production.

    This previously asserted the bracketed literal appears in the policy. A
    browser drops that source entirely, so the policy behaved as `'self'` while
    reading as though the endpoint were allowed — the test pinned output that
    could not work. Falling back to `'self'` is the same effective behaviour,
    stated honestly.
    """
    csp = _csp_for_endpoint(monkeypatch, tmp_path, "https://[2001:db8::1]:9000")

    assert "2001:db8" not in csp, csp
    assert "connect-src 'self'" in csp, csp


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

    def test_a_malformed_tenant_endpoint_degrades_instead_of_raising(self) -> None:
        """``_storage_origins`` has no guard of its own, so the ValueError must be caught below it.

        ``ManagedStorageConfig`` does not validate ``endpoint_url``, and
        ``urlparse("http://[evil")`` raises ``ValueError: Invalid IPv6 URL``.
        Without the try/except in ``storage_origins_for_config`` this raises
        inside ``SecurityHeadersMiddleware.dispatch`` — a 500 on every request
        for that tenant. The standalone path hides this behind its own blanket
        ``except``, so only the per-tenant call proves the guard is load-bearing.
        """
        from types import SimpleNamespace

        from publisher_v2.web.middleware_security import _storage_origins

        request = SimpleNamespace(
            state=SimpleNamespace(config=self._config("http://[evil")),
            app=SimpleNamespace(state=SimpleNamespace(csp_storage_origins=["https://instance.example"])),
        )

        assert _storage_origins(request) == []


class TestOrchestratedRequestReachesTheHeader:
    """#144 item 1: the tenant config set by the inner middleware must be visible to the outer one.

    `TestPerTenantOrigins` fakes the request, so it cannot prove that
    `SecurityHeadersMiddleware` (outermost) can read `request.state.config`
    written by `tenant_middleware` (innermost) after `call_next`. That works
    today only because Starlette backs `request.state` with `scope["state"]`;
    a middleware-ordering or Starlette change would silently drop every
    orchestrated tenant back to the standalone snapshot.
    """

    def test_the_tenant_origin_reaches_the_served_policy(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        from types import SimpleNamespace

        from fastapi.testclient import TestClient

        env = _base_env(tmp_path) | {
            "STORAGE_PROVIDER": "dropbox",
            "DROPBOX_APP_KEY": "k",
            "DROPBOX_APP_SECRET": "s",
            "DROPBOX_REFRESH_TOKEN": "r",
            "ORCHESTRATOR_BASE_URL": "https://orchestrator.example",
        }
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("CONFIG_SOURCE", raising=False)

        tenant_config = TestPerTenantOrigins._config("https://tenant-account.r2.cloudflarestorage.com")
        runtime = SimpleNamespace(host="tenant.example", tenant="tenant-1", config=tenant_config)

        class _Source:
            async def get_config(self, host: str) -> Any:
                return runtime

        class _Factory:
            async def get_service(self, source: Any, runtime_config: Any) -> Any:
                return SimpleNamespace(config=runtime_config.config)

        from publisher_v2.config.source import get_config_source
        from publisher_v2.web.app import app, get_service

        get_config_source.cache_clear()
        get_service.cache_clear()
        with (
            patch("publisher_v2.web.middleware.get_config_source", lambda: _Source()),
            patch("publisher_v2.web.middleware._tenant_service_factory", lambda _settings=None: _Factory()),
            patch("publisher_v2.services.storage.dropbox.Dropbox"),
            TestClient(app) as client,
        ):
            response = client.get("/", headers={"host": "tenant.example"})
        csp = response.headers["Content-Security-Policy"]
        get_config_source.cache_clear()
        get_service.cache_clear()
        with contextlib.suppress(Exception):
            get_service()

        assert "tenant-account.r2.cloudflarestorage.com" in csp, csp
        # The standalone snapshot for this env is the Dropbox content origin;
        # seeing it here would mean the tenant config never reached the header.
        assert "dropbox" not in csp, csp
        assert not _has_blanket_https(csp), csp


class TestRejectedEndpointIsVisibleToOperators:
    """#144 follow-up: a rejected endpoint must leave a server-side signal — once."""

    @staticmethod
    def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
        return [r.getMessage() for r in caplog.records if "csp_storage_origin_rejected" in r.getMessage()]

    @pytest.fixture(autouse=True)
    def _clear_dedup(self) -> Iterator[None]:
        from publisher_v2.web.middleware_security import _log_rejected_origin

        # Tolerate the de-dup being gone so its own test fails on the count
        # rather than erroring in setup.
        clear = getattr(_log_rejected_origin, "cache_clear", lambda: None)
        clear()
        yield
        clear()

    def test_an_unusable_endpoint_logs_a_warning_without_the_value(self, caplog: pytest.LogCaptureFixture) -> None:
        from publisher_v2.web.middleware_security import storage_origins_for_config

        caplog.set_level(logging.WARNING, logger="publisher_v2.web")
        config = TestPerTenantOrigins._config("https://evil.example; script-src *")

        assert storage_origins_for_config(config) == []

        events = self._warnings(caplog)
        assert events, caplog.text
        assert '"scheme": "https"' in events[0]
        # The netloc is tenant-supplied: a fingerprint may be logged, never the
        # value, and never its length (a length oracle over any userinfo in it).
        assert "evil.example" not in events[0]
        assert "script-src" not in events[0]
        assert "netloc_length" not in events[0]

    def test_an_unparseable_endpoint_is_logged_too(self, caplog: pytest.LogCaptureFixture) -> None:
        """The branch an operator is most likely to hit must not be the silent one."""
        from publisher_v2.web.middleware_security import storage_origins_for_config

        caplog.set_level(logging.WARNING, logger="publisher_v2.web")
        config = TestPerTenantOrigins._config("http://[evil")

        assert storage_origins_for_config(config) == []

        events = self._warnings(caplog)
        assert events, caplog.text
        assert '"scheme": "unparseable"' in events[0]
        assert "evil" not in events[0]

    def test_the_warning_does_not_repeat_on_every_request(self, caplog: pytest.LogCaptureFixture) -> None:
        """The helper runs per response; one broken tenant must not log per request."""
        from publisher_v2.web.middleware_security import storage_origins_for_config

        caplog.set_level(logging.WARNING, logger="publisher_v2.web")
        config = TestPerTenantOrigins._config("https://evil.example; script-src *")
        other = TestPerTenantOrigins._config("https://other.example; script-src *")

        for _ in range(5):
            storage_origins_for_config(config)

        assert len(self._warnings(caplog)) == 1, caplog.text

        storage_origins_for_config(other)

        assert len(self._warnings(caplog)) == 2, "a different endpoint is a different signal"

    def test_a_long_hostile_scheme_is_truncated(self, caplog: pytest.LogCaptureFixture) -> None:
        """The scheme is tenant-controlled and unbounded: urlparse returns whatever precedes "://"."""
        from publisher_v2.web.middleware_security import storage_origins_for_config

        caplog.set_level(logging.WARNING, logger="publisher_v2.web")
        config = TestPerTenantOrigins._config("a" * 100 + "x://host")

        assert storage_origins_for_config(config) == []

        events = self._warnings(caplog)
        assert events, caplog.text
        assert "a" * 100 not in events[0]
        logged = json.loads(events[0])["scheme"]
        assert len(logged) == 16, logged


class TestTheRejectionSignalIsActionable:
    """#144 security audit: the WARNING named no tenant, so an operator could not act on it.

    The event said "some tenant's storage origin was dropped" and gave an 8-hex
    fingerprint that maps to nothing an operator holds. On a fleet the signal
    was unusable. The tenant id is not secret — the endpoint is what must never
    be logged — so it goes in the event and in the de-dup key.
    """

    @staticmethod
    def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
        return [r.getMessage() for r in caplog.records if "csp_storage_origin_rejected" in r.getMessage()]

    @pytest.fixture(autouse=True)
    def _clear_dedup(self) -> Iterator[None]:
        from publisher_v2.web.middleware_security import _log_rejected_origin

        clear = getattr(_log_rejected_origin, "cache_clear", lambda: None)
        clear()
        yield
        clear()

    def test_the_warning_names_the_tenant(self, caplog: pytest.LogCaptureFixture) -> None:
        from publisher_v2.web.middleware_security import storage_origins_for_config

        caplog.set_level(logging.WARNING, logger="publisher_v2.web")
        config = TestPerTenantOrigins._config("https://evil.example; script-src *")

        assert storage_origins_for_config(config, tenant="acme") == []

        events = self._warnings(caplog)
        assert events, caplog.text
        assert '"tenant": "acme"' in events[0]
        assert "evil.example" not in events[0]

    def test_two_tenants_sharing_a_broken_endpoint_are_both_reported(self, caplog: pytest.LogCaptureFixture) -> None:
        """De-dup is per signal, not per endpoint: each tenant needs its own line to act on."""
        from publisher_v2.web.middleware_security import storage_origins_for_config

        caplog.set_level(logging.WARNING, logger="publisher_v2.web")
        config = TestPerTenantOrigins._config("https://evil.example; script-src *")

        storage_origins_for_config(config, tenant="acme")
        storage_origins_for_config(config, tenant="globex")
        storage_origins_for_config(config, tenant="acme")

        events = self._warnings(caplog)
        assert len(events) == 2, caplog.text
        assert any('"tenant": "acme"' in e for e in events)
        assert any('"tenant": "globex"' in e for e in events)

    def test_the_request_path_passes_the_tenant_through(self, caplog: pytest.LogCaptureFixture) -> None:
        """The value has to reach the helper from the request, not just be accepted by it."""
        from types import SimpleNamespace

        from publisher_v2.web.middleware_security import _storage_origins

        caplog.set_level(logging.WARNING, logger="publisher_v2.web")
        request = SimpleNamespace(
            state=SimpleNamespace(
                config=TestPerTenantOrigins._config("https://evil.example; script-src *"),
                tenant="acme",
            ),
            app=SimpleNamespace(state=SimpleNamespace(csp_storage_origins=[])),
        )

        assert _storage_origins(request) == []  # type: ignore[arg-type]

        events = self._warnings(caplog)
        assert events, caplog.text
        assert '"tenant": "acme"' in events[0]


class TestAnEndpointCannotInflateTheHeader:
    """#144 security audit: the accepted netloc had no length bound.

    ``https://<100k chars>.com`` matched the safe-netloc pattern, so the origin
    was emitted twice per response — img-src and connect-src — giving that
    tenant a ~200KB CSP header on every response, which many reverse proxies
    answer with a 502. Self-inflicted and tenant-scoped, but free to prevent.
    """

    def test_an_absurdly_long_host_is_rejected(self) -> None:
        from publisher_v2.web.middleware_security import storage_origins_for_config

        config = TestPerTenantOrigins._config("https://" + "a" * 100_000 + ".com")
        assert storage_origins_for_config(config) == []

    def test_a_host_at_the_dns_limit_is_still_accepted(self) -> None:
        """253 is the DNS name limit; the bound must not reject a legal host."""
        from publisher_v2.web.middleware_security import storage_origins_for_config

        host = ("a" * 49 + ".") * 5 + "com"  # 253 characters
        assert len(host) == 253
        config = TestPerTenantOrigins._config(f"https://{host}")
        assert storage_origins_for_config(config) == [f"https://{host}"]

    def test_an_ordinary_host_with_a_port_still_works(self) -> None:
        from publisher_v2.web.middleware_security import storage_origins_for_config

        config = TestPerTenantOrigins._config("https://minio.internal:9000")
        assert storage_origins_for_config(config) == ["https://minio.internal:9000"]
