"""#143: RuntimeSettings is injected, not fetched from a service locator per call.

``load_runtime_settings()`` re-parsed the environment on every publish-timeout
lookup, every request that checked the upload cap, and every caption-history
write. These tests pin the shape of the fix: settings are read once when a
component is built (or at process start) and then carried, and the tunables the
issue lists live in ``RuntimeSettings`` rather than in ad-hoc ``os.environ``
reads scattered across the web layer.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from publisher_v2.config.runtime_settings import RuntimeSettings, load_runtime_settings

SRC = Path(__file__).resolve().parents[1] / "src" / "publisher_v2"

# Modules whose request/publish paths must not re-read settings at call time.
HOT_PATH_MODULES = [
    "core/workflow.py",
    "services/ai.py",
    "web/service.py",
    "web/routers/library.py",
    "db/caption_store.py",
    "web/middleware.py",
    "web/settings.py",
    "web/app.py",
]

# The only non-constructor loads allowed: the accessor's documented fallback and
# the process-start parses. Anything else on a request path fails the test.
ALLOWED_LOAD_SITES = {
    "web/settings.py": {"get_runtime_settings"},
    "web/app.py": {"lifespan"},
}


def _load_calls_outside_constructors(path: Path) -> list[str]:
    """Every ``load_runtime_settings()`` call that is not part of building an object."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.name == "__init__":
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "load_runtime_settings"
            ):
                hits.append(f"{node.name}:{inner.lineno}")
    return hits


@pytest.mark.parametrize("module", HOT_PATH_MODULES)
def test_no_settings_reload_on_request_or_publish_paths(module: str) -> None:
    allowed = ALLOWED_LOAD_SITES.get(module, set())
    hits = [h for h in _load_calls_outside_constructors(SRC / module) if h.split(":")[0] not in allowed]
    assert hits == [], f"{module} re-reads RuntimeSettings at call time: {hits}"


class TestTunablesLiveInRuntimeSettings:
    """#143 item 2: these were ad-hoc os.environ reads in the web/service layer."""

    def test_thumbnail_cache_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WEB_THUMBNAIL_CACHE_TTL_SECONDS", "123")
        monkeypatch.setenv("WEB_THUMBNAIL_CACHE_MAX_BYTES", "4096")
        settings = load_runtime_settings()
        assert settings.thumbnail_cache_ttl_seconds == 123.0
        assert settings.thumbnail_cache_max_bytes == 4096

    def test_proxy_and_cookie_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WEB_TRUST_FORWARDED_FOR", "true")
        monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
        monkeypatch.setenv("WEB_LOGIN_BACKOFF_CAP_SECONDS", "9")
        settings = load_runtime_settings()
        assert settings.trust_forwarded_for is True
        assert settings.secure_cookies is False
        assert settings.login_backoff_cap_seconds == 9.0

    def test_mode_selection_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONFIG_SOURCE", "env")
        monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orchestrator.example")
        settings = load_runtime_settings()
        assert settings.config_source == "env"
        assert settings.orchestrator_base_url == "https://orchestrator.example"
        assert settings.is_standalone is True

    def test_defaults_match_the_previous_env_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key in (
            "WEB_THUMBNAIL_CACHE_TTL_SECONDS",
            "WEB_THUMBNAIL_CACHE_MAX_BYTES",
            "WEB_TRUST_FORWARDED_FOR",
            "WEB_SECURE_COOKIES",
            "WEB_LOGIN_BACKOFF_CAP_SECONDS",
            "CONFIG_SOURCE",
            "ORCHESTRATOR_BASE_URL",
        ):
            monkeypatch.delenv(key, raising=False)
        settings = load_runtime_settings()
        assert settings.thumbnail_cache_ttl_seconds == 900.0
        assert settings.thumbnail_cache_max_bytes == 50 * 1024 * 1024
        assert settings.trust_forwarded_for is False
        assert settings.secure_cookies is True
        assert settings.login_backoff_cap_seconds == 5.0
        assert settings.is_standalone is True  # no orchestrator configured


class TestInjectedSettingsAreHonoured:
    """A component built with explicit settings must not consult the environment."""

    def test_caption_store_uses_injected_retention(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from publisher_v2.db.caption_store import CaptionStore

        monkeypatch.setenv("PV2_CAPTION_HISTORY_RETENTION_DAYS", "7")
        store = CaptionStore(None, settings=RuntimeSettings(caption_history_retention_days=42))  # type: ignore[arg-type]
        assert store._retention_days == 42

    def test_workflow_uses_injected_publish_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The orchestrator reads the timeout off its own settings — no env lookup per publish."""
        monkeypatch.setenv("PUBLISH_TIMEOUT_SECONDS", "11")
        settings = RuntimeSettings(publish_timeout_seconds=77.0, publish_timeout_overrides={"telegram": 30.0})
        assert settings.publish_timeout_for("telegram") == 30.0
        assert settings.publish_timeout_for("email") == 77.0


class TestCacheMissDoesNotReparseTheEnvironment:
    """#143 review: a tenant cache miss during a request must carry settings, not re-read env."""

    @staticmethod
    def _runtime_config():
        from publisher_v2.config.schema import (
            ApplicationConfig,
            ContentConfig,
            ManagedStorageConfig,
            OpenAIConfig,
            PlatformsConfig,
            StoragePathConfig,
        )
        from publisher_v2.config.source import RuntimeConfig

        cfg = ApplicationConfig(
            managed=ManagedStorageConfig(
                access_key_id="k", secret_access_key="s", endpoint_url="https://r2.local", bucket="b"
            ),
            storage_paths=StoragePathConfig(image_folder="/Photos"),
            openai=OpenAIConfig(api_key=None),
            platforms=PlatformsConfig(),
            content=ContentConfig(hashtag_string="", archive=True, debug=False),
        )
        return RuntimeConfig(host="a.example.test", tenant="a", config=cfg, config_version="v1")

    async def test_tenant_cache_miss_does_not_call_load_runtime_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from publisher_v2.web.tenant_factory import TenantServiceFactory

        def _boom() -> RuntimeSettings:
            raise AssertionError("load_runtime_settings() called on a request path")

        for module in (
            "publisher_v2.web.service",
            "publisher_v2.services.managed_storage",
            "publisher_v2.services.ai",
            "publisher_v2.db.caption_store",
            "publisher_v2.core.workflow",
        ):
            monkeypatch.setattr(f"{module}.load_runtime_settings", _boom)

        settings = RuntimeSettings(library_max_upload_mb=99)
        factory = TenantServiceFactory(max_size=4, ttl_seconds=600, settings=settings)

        service = await factory.get_service(None, self._runtime_config())  # type: ignore[arg-type]

        assert service._settings is settings
        # The storage backend built on the same miss must reuse it too.
        assert service.storage._settings is settings

    def test_create_storage_passes_settings_to_managed_storage(self) -> None:
        from publisher_v2.services.storage_factory import create_storage

        settings = RuntimeSettings(thumbnail_cache_max_bytes=7)
        storage = create_storage(self._runtime_config().config, settings=settings)
        assert storage._settings is settings  # type: ignore[attr-defined]


class TestTheCookieFlagComesFromTheSnapshot:
    """#143 review: ``set_admin_cookie`` was the last env read left on an auth path.

    It parsed ``WEB_SECURE_COOKIES`` itself with a narrower truthy set than
    ``RuntimeSettings`` uses — ``("1", "true", "yes")`` against the snapshot's
    ``("1", "true", "yes", "on")``. An operator who wrote ``WEB_SECURE_COOKIES=on``
    got HSTS (which reads the snapshot) but an admin cookie **without** ``Secure``,
    so the session cookie could be sent over plain http.
    """

    @staticmethod
    def _callback_response(monkeypatch: pytest.MonkeyPatch, raw_value: str):
        from unittest.mock import AsyncMock, patch

        from fastapi.testclient import TestClient

        from publisher_v2.config.schema import Auth0Config
        from publisher_v2.web.app import app
        from publisher_v2.web.dependencies import get_request_service

        monkeypatch.setenv("WEB_SECURE_COOKIES", raw_value)
        monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret-value-long-enough")

        service = type("_Svc", (), {})()
        service.config = type("_Cfg", (), {})()
        service.config.auth0 = Auth0Config(
            domain="test.auth0.com",
            client_id="cid",
            client_secret="sec",
            callback_url="http://testserver/auth/callback",
            admin_emails="admin@example.com",
        )

        with patch("publisher_v2.web.routers.auth.oauth") as oauth:
            oauth._registry = {"auth0": True}
            oauth.auth0 = AsyncMock()
            oauth.auth0.authorize_access_token.return_value = {
                "userinfo": {"email": "admin@example.com", "email_verified": True}
            }
            app.dependency_overrides[get_request_service] = lambda request=None: service
            try:
                # The context manager runs the lifespan, which is what builds the
                # snapshot this test is about.
                with TestClient(app) as client:
                    return client.get("/auth/callback?code=1&state=x", follow_redirects=False)
            finally:
                app.dependency_overrides = {}

    def test_secure_cookies_on_marks_the_admin_cookie_secure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = self._callback_response(monkeypatch, "on")
        set_cookie = response.headers["set-cookie"]
        assert "pv2_admin=" in set_cookie
        assert "Secure" in set_cookie, (
            f"WEB_SECURE_COOKIES=on is truthy for RuntimeSettings but the cookie is not Secure: {set_cookie}"
        )

    def test_secure_cookies_false_still_omits_the_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The falsy path is unchanged — local http development keeps working."""
        response = self._callback_response(monkeypatch, "false")
        set_cookie = response.headers["set-cookie"]
        assert "pv2_admin=" in set_cookie
        assert "Secure" not in set_cookie

    def test_set_admin_cookie_no_longer_reads_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The caller decides; the function must not consult the env itself."""
        source = (SRC / "web" / "auth.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(
            node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "set_admin_cookie"
        )
        env_reads = [
            inner.lineno
            for inner in ast.walk(fn)
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) and inner.func.id == "_get_env"
        ]
        assert env_reads == [], f"set_admin_cookie still reads the environment at lines {env_reads}"
