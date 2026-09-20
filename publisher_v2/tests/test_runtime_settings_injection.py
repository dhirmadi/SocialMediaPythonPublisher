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


def _is_env_reparse(call: ast.Call) -> bool:
    """A call that parses the environment instead of reading an injected snapshot.

    Three shapes, not one: the bare name, the attribute form
    (``runtime_settings.load_runtime_settings()``), and ``get_runtime_settings()``
    with no request — the accessor's documented fallback *is* a fresh parse, so a
    no-argument call is a service locator wearing the accessor's name.
    """
    func = call.func
    name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
    if name == "load_runtime_settings":
        return True
    return name == "get_runtime_settings" and not call.args and not call.keywords


def _load_calls_outside_constructors(path: Path) -> list[str]:
    """Every environment re-parse that is not part of building an object."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.name == "__init__":
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and _is_env_reparse(inner):
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
        settings = load_runtime_settings()
        assert settings.trust_forwarded_for is True
        assert settings.secure_cookies is False

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
            "CONFIG_SOURCE",
            "ORCHESTRATOR_BASE_URL",
        ):
            monkeypatch.delenv(key, raising=False)
        settings = load_runtime_settings()
        assert settings.thumbnail_cache_ttl_seconds == 900.0
        assert settings.thumbnail_cache_max_bytes == 50 * 1024 * 1024
        assert settings.trust_forwarded_for is False
        assert settings.secure_cookies is True
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
                app.dependency_overrides.clear()

    def test_secure_cookies_on_marks_the_admin_cookie_secure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = self._callback_response(monkeypatch, "on")
        set_cookie = response.headers["set-cookie"]
        assert "pv2_admin=" in set_cookie
        assert "Secure" in set_cookie, (
            f"WEB_SECURE_COOKIES=on is truthy for RuntimeSettings but the cookie is not Secure: {set_cookie}"
        )

    def test_a_padded_value_still_marks_the_cookie_secure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The whole point of the parity rule, asserted on the header the browser sees."""
        set_cookie = self._callback_response(monkeypatch, "true ").headers["set-cookie"]
        assert "pv2_admin=" in set_cookie
        assert "Secure" in set_cookie, set_cookie

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


class TestPaddedValuesKeepTheirOldMeaning:
    """Security audit of #143: the two historical parsers did not agree on whitespace.

    ``set_admin_cookie`` read ``WEB_SECURE_COOKIES`` through ``web/auth.py::_get_env``,
    which strips and treats a whitespace-only value as unset, so ``"true "`` — a
    trailing space in a Heroku config var or a ``.env`` line — meant **on**.
    ``RuntimeSettings`` does not strip, so moving the read would have turned that
    same value **off** and minted the admin cookie without ``Secure``.

    ``WEB_TRUST_FORWARDED_FOR`` is the opposite case: it was never read through
    ``_get_env`` (``rate_limit.py`` used a bare ``os.environ.get``), so a padded
    value has always been falsy there, and it must stay falsy — that direction
    errs toward not trusting proxy-supplied headers.
    """

    @pytest.mark.parametrize("raw", ["true ", " true", "  TRUE  ", "on "])
    def test_padded_secure_cookies_is_still_on(self, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
        monkeypatch.setenv("WEB_SECURE_COOKIES", raw)
        assert load_runtime_settings().secure_cookies is True

    @pytest.mark.parametrize("raw", ["   ", "\t"])
    def test_whitespace_only_secure_cookies_falls_back_to_the_default(
        self, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        """``_get_env`` treated whitespace-only as unset, and the default is on."""
        monkeypatch.setenv("WEB_SECURE_COOKIES", raw)
        assert load_runtime_settings().secure_cookies is True

    @pytest.mark.parametrize("raw", ["false ", " false", "  0  "])
    def test_padded_falsy_secure_cookies_is_still_off(self, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
        monkeypatch.setenv("WEB_SECURE_COOKIES", raw)
        assert load_runtime_settings().secure_cookies is False

    @pytest.mark.parametrize("raw", ["true ", " true"])
    def test_padded_trust_forwarded_for_stays_off(self, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
        """Unchanged from main: a padded value never trusted the proxy headers."""
        monkeypatch.setenv("WEB_TRUST_FORWARDED_FOR", raw)
        assert load_runtime_settings().trust_forwarded_for is False


class TestTheSharedSnapshotCannotBeMutated:
    """Security audit of #143: ``frozen=True`` blocks attribute assignment only.

    The snapshot is process-wide — every tenant's ``WebImageService`` holds the
    same instance — so a mutable field on it is a cross-tenant channel:
    ``settings.publish_timeout_overrides["telegram"] = 9999`` would change the
    publish timeout for every tenant in the process.
    """

    def test_attribute_assignment_is_refused(self) -> None:
        from pydantic import ValidationError

        settings = load_runtime_settings()
        with pytest.raises(ValidationError):
            settings.secure_cookies = False  # type: ignore[misc]

    def test_publish_timeout_overrides_cannot_be_written_through(self) -> None:
        settings = RuntimeSettings(publish_timeout_overrides={"telegram": 30.0})
        with pytest.raises(TypeError):
            settings.publish_timeout_overrides["telegram"] = 9999.0  # type: ignore[index]
        assert settings.publish_timeout_for("telegram") == 30.0

    def test_the_override_mapping_still_reads_normally(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PUBLISH_TIMEOUT_TELEGRAM_SECONDS", "30")
        settings = load_runtime_settings()
        assert settings.publish_timeout_for("telegram") == 30.0
        assert settings.publish_timeout_for("email") == settings.publish_timeout_seconds
        assert dict(settings.publish_timeout_overrides) == {"telegram": 30.0}


class TestTheSnapshotSurvivesOrdinaryHandling:
    """Follow-up audit of #143: ``MappingProxyType`` made the model unusable in ways nothing catches.

    A snapshot that cannot be deep-copied, pickled or serialised is a latent
    failure in code that does not exist yet — a debug ``model_dump_json()`` in a
    log line would 500 the request, and ``model_copy(deep=True)`` is already the
    idiom one module over. The overrides are stored as a tuple of pairs instead:
    immutable, and none of that breaks.
    """

    def test_deep_copy_pickle_and_json_all_work(self) -> None:
        import copy
        import pickle

        settings = RuntimeSettings(publish_timeout_overrides={"telegram": 30.0})
        assert copy.deepcopy(settings).publish_timeout_for("telegram") == 30.0
        assert settings.model_copy(deep=True).publish_timeout_for("telegram") == 30.0
        # S301: round-tripping a model this test just built, not untrusted input.
        assert pickle.loads(pickle.dumps(settings)).publish_timeout_for("telegram") == 30.0  # noqa: S301
        assert "telegram" in settings.model_dump_json()

    def test_the_snapshot_is_hashable(self) -> None:
        """``frozen=True`` advertises hashability; a cache keyed on settings must not blow up."""
        settings = RuntimeSettings(publish_timeout_overrides={"telegram": 30.0})
        assert len({settings, settings.model_copy()}) == 1

    def test_the_overrides_still_cannot_be_written_through(self) -> None:
        settings = RuntimeSettings(publish_timeout_overrides={"telegram": 30.0})
        with pytest.raises(TypeError):
            settings.publish_timeout_overrides["telegram"] = 9999.0  # type: ignore[index]
        assert settings.publish_timeout_for("telegram") == 30.0


class TestTheRemovedLoginBackoffKnobStaysRemoved:
    """#137 deleted the password login and ``WEB_LOGIN_BACKOFF_CAP_SECONDS`` with it.

    #143 re-added it to ``RuntimeSettings`` as a parsed field with no consumer,
    while ``CONFIGURATION.md`` and ``SPECIFICATION.md`` both say it no longer
    exists. An inert knob tied to a deliberately removed auth path still reads
    as supported.
    """

    def test_runtime_settings_has_no_login_backoff_field(self) -> None:
        assert "login_backoff_cap_seconds" not in RuntimeSettings.model_fields

    def test_the_env_var_is_not_read_anywhere_in_the_source(self) -> None:
        hits = [
            path.relative_to(SRC).as_posix()
            for path in SRC.rglob("*.py")
            if "WEB_LOGIN_BACKOFF_CAP_SECONDS" in path.read_text(encoding="utf-8")
        ]
        assert hits == [], f"#137 removed this knob; it is still read in {hits}"
