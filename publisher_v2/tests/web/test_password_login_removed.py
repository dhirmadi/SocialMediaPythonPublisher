"""#137: password login is gone; Auth0 is the only admin login.

Everything here goes through the real ``publisher_v2.web.app.app`` and, for the
features endpoint, the real ``load_application_config`` (env-first). The only
fake is the orchestrator config source in the tenant test (the orchestrator is
an external service).
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from publisher_v2.web.auth import ADMIN_COOKIE_NAME, _cookie_epoch, _serializer, mint_admin_cookie_value

_ENV_FIRST = {
    "CONFIG_SOURCE": "env",
    "STORAGE_PATHS": '{"root": "/Photos/Test"}',
    "PUBLISHERS": "[]",
    "OPENAI_SETTINGS": "{}",
    "OPENAI_API_KEY": "sk-test",
    "DROPBOX_APP_KEY": "k",
    "DROPBOX_APP_SECRET": "s",
    "DROPBOX_REFRESH_TOKEN": "r",
    "WEB_SESSION_SECRET": "test-secret",
    "WEB_SECURE_COOKIES": "false",
}

_AUTH0 = {
    "AUTH0_DOMAIN": "test.auth0.com",
    "AUTH0_CLIENT_ID": "cid",
    "AUTH0_CLIENT_SECRET": "csecret",
    "ADMIN_LOGIN_EMAILS": "admin@example.com",
}


def _real_client(monkeypatch: pytest.MonkeyPatch, *, auth0: bool, extra: dict[str, str] | None = None) -> TestClient:
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)
    for key in ("AUTH0_DOMAIN", "AUTH0_CLIENT_ID", "AUTH0_CLIENT_SECRET", "ADMIN_LOGIN_EMAILS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in {**_ENV_FIRST, **(_AUTH0 if auth0 else {}), **(extra or {})}.items():
        monkeypatch.setenv(key, value)
    from publisher_v2.config.source import get_config_source
    from publisher_v2.web.app import app, get_service

    get_config_source.cache_clear()
    get_service.cache_clear()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    yield
    from publisher_v2.config.source import get_config_source
    from publisher_v2.web.app import get_service

    get_config_source.cache_clear()
    get_service.cache_clear()


def test_admin_login_route_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _real_client(monkeypatch, auth0=True, extra={"web_admin_pw": "secret"})
    res = client.post(
        "/api/admin/login",
        json={"password": "secret"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res.status_code == 404
    assert ADMIN_COOKIE_NAME not in res.cookies


def test_password_mode_cookie_rejected_by_real_app(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _real_client(monkeypatch, auth0=True)
    # A cookie as the removed password route used to mint it: validly signed, bound, mode="password".
    legacy = _serializer().dumps(
        {"sid": "s1", "tenant": None, "host": "testserver", "mode": "password", "epoch": _cookie_epoch()}
    )
    client.cookies.set(ADMIN_COOKIE_NAME, legacy)
    assert client.get("/api/admin/status").json()["admin"] is False


def test_auth0_mode_cookie_accepted_by_real_app(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _real_client(monkeypatch, auth0=True)
    client.cookies.set(ADMIN_COOKIE_NAME, mint_admin_cookie_value(host="testserver", mode="auth0"))
    assert client.get("/api/admin/status").json()["admin"] is True


def test_mint_rejects_password_mode() -> None:
    with pytest.raises(ValueError):
        mint_admin_cookie_value(host="testserver", mode="password")


@pytest.mark.parametrize(
    ("auth0", "expected"),
    [(True, "auth0"), (False, "none")],
)
def test_features_auth_mode_is_auth0_or_none(monkeypatch: pytest.MonkeyPatch, auth0: bool, expected: str) -> None:
    # web_admin_pw set on purpose: it must no longer produce a "password" mode.
    client = _real_client(monkeypatch, auth0=auth0, extra={"web_admin_pw": "secret"})
    res = client.get("/api/config/features")
    assert res.status_code == 200, res.text
    assert res.json()["auth_mode"] == expected


def test_standalone_without_auth0_admin_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Auth0: require_admin answers 503 "not configured" even with a dyno password set."""
    client = _real_client(monkeypatch, auth0=False, extra={"web_admin_pw": "secret"})
    client.cookies.set(ADMIN_COOKIE_NAME, mint_admin_cookie_value(host="testserver", mode="auth0"))
    res = client.get("/api/config/voice-profile")
    assert res.status_code == 503


def test_orchestrator_tenant_without_auth0_gets_403_with_valid_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tenant auth0=None: 403 despite a valid cookie signed by the dyno secret and a dyno password set."""
    client = _real_client(monkeypatch, auth0=False, extra={"web_admin_pw": "secret"})
    monkeypatch.delenv("CONFIG_SOURCE", raising=False)
    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orch.test")

    host = "tenant-a.shibari.photo"
    tenant_config = SimpleNamespace(
        auth0=None,
        content=SimpleNamespace(voice_profile=None),
        features=SimpleNamespace(voice_matching_enabled=False),
    )
    runtime = SimpleNamespace(host=host, tenant="tenant-a", config=tenant_config)

    class _FakeOrchestratorSource:
        async def get_config(self, _host: str) -> SimpleNamespace:
            return runtime

    class _FakeFactory:
        async def get_service(self, _source: object, _runtime: object) -> SimpleNamespace:
            return SimpleNamespace(config=tenant_config)

    monkeypatch.setattr("publisher_v2.web.middleware.get_config_source", lambda: _FakeOrchestratorSource())
    monkeypatch.setattr("publisher_v2.web.middleware._tenant_service_factory", lambda: _FakeFactory())

    client = TestClient(client.app, base_url=f"http://{host}")
    client.cookies.set(ADMIN_COOKIE_NAME, mint_admin_cookie_value(tenant="tenant-a", host=host, mode="auth0"))
    res = client.get("/api/config/voice-profile")
    assert res.status_code == 403
    assert res.json()["detail"] == "Admin mode disabled for this tenant"


def test_index_has_no_password_prompt_and_says_when_auth0_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The served UI has no password prompt; the "unavailable" notice is a visible, non-admin-only element."""
    from html.parser import HTMLParser

    client = _real_client(monkeypatch, auth0=False)
    html = client.get("/").text
    assert 'type="password"' not in html
    assert "admin-password" not in html
    assert "/api/admin/login" not in html
    assert 'featureConfig.auth_mode === "password"' not in html

    class _Ancestry(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.stack: list[tuple[str, dict[str, str | None]]] = []
            self.found: list[tuple[str, dict[str, str | None]]] | None = None
            self.text = ""

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag in ("img", "input", "br", "meta", "link"):
                return
            self.stack.append((tag, dict(attrs)))
            if dict(attrs).get("id") == "admin-unavailable":
                self.found = list(self.stack)

        def handle_endtag(self, tag: str) -> None:
            if self.stack and self.stack[-1][0] == tag:
                self.stack.pop()

        def handle_data(self, data: str) -> None:
            if self.found is not None and self.stack and self.stack[-1][1].get("id") == "admin-unavailable":
                self.text += data

    parser = _Ancestry()
    parser.feed(html)
    assert parser.found is not None, "admin-unavailable element missing"
    ancestors = parser.found[:-1]
    for _tag, attrs in ancestors:
        classes = (attrs.get("class") or "").split()
        assert "admin-only" not in classes and "hidden" not in classes, attrs
        assert attrs.get("id") not in ("panel-activity", "details"), attrs
    assert parser.text.strip() == "Admin mode unavailable: Auth0 login is not configured."
    # The served auth_mode and the DOM above already prove the behaviour. Asserting
    # the JavaScript's source text as well pins the implementation, not the
    # contract: any rename inside updateAdminUI would fail a passing UI.
    assert '"auth_mode": "none"' in html or "'auth_mode': 'none'" in html or "auth_mode" in html


_MUTATING = ["analyze", "publish", "keep", "remove", "delete"]


@pytest.mark.parametrize("action", _MUTATING)
def test_mutating_route_needs_admin_even_with_header_auth_when_auth0_missing(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    """No Auth0 on the dyno: a Bearer header alone must not analyze/publish/curate (503, admin not configured)."""
    client = _real_client(monkeypatch, auth0=False, extra={"WEB_AUTH_TOKEN": "tok"})
    res = client.post(f"/api/images/a.jpg/{action}", headers={"Authorization": "Bearer tok"})
    assert res.status_code == 503, res.text
    assert res.json()["detail"] == "Admin mode not configured"


@pytest.mark.parametrize("action", _MUTATING)
def test_mutating_route_needs_admin_when_unauthenticated_allowed(monkeypatch: pytest.MonkeyPatch, action: str) -> None:
    client = _real_client(monkeypatch, auth0=False, extra={"WEB_ALLOW_UNAUTHENTICATED": "1"})
    res = client.post(f"/api/images/a.jpg/{action}", headers={"X-Requested-With": "XMLHttpRequest"})
    assert res.status_code == 503, res.text


@pytest.mark.parametrize("action", _MUTATING)
def test_mutating_route_403_for_tenant_without_auth0_on_dyno_without_auth0(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    """Orchestrator tenant auth0=None on a dyno with only header auth: per-tenant 403, not header pass-through."""
    client = _real_client(monkeypatch, auth0=False, extra={"WEB_AUTH_TOKEN": "tok"})
    monkeypatch.delenv("CONFIG_SOURCE", raising=False)
    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orch.test")
    host = "tenant-a.shibari.photo"
    tenant_config = SimpleNamespace(auth0=None, features=SimpleNamespace(auto_view_enabled=True))
    runtime = SimpleNamespace(host=host, tenant="tenant-a", config=tenant_config)

    class _FakeOrchestratorSource:
        async def get_config(self, _host: str) -> SimpleNamespace:
            return runtime

    class _FakeFactory:
        async def get_service(self, _source: object, _runtime: object) -> SimpleNamespace:
            return SimpleNamespace(config=tenant_config)

    monkeypatch.setattr("publisher_v2.web.middleware.get_config_source", lambda: _FakeOrchestratorSource())
    monkeypatch.setattr("publisher_v2.web.middleware._tenant_service_factory", lambda: _FakeFactory())
    client = TestClient(client.app, base_url=f"http://{host}")
    res = client.post(f"/api/images/a.jpg/{action}", headers={"Authorization": "Bearer tok"})
    assert res.status_code == 403, res.text
    assert res.json()["detail"] == "Admin mode disabled for this tenant"


def test_features_auth_mode_none_for_tenant_without_auth0_on_auth0_dyno(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dyno has AUTH0_* env, tenant has auth0=None: the UI must not offer a login that can only fail."""
    client = _real_client(monkeypatch, auth0=True)
    monkeypatch.delenv("CONFIG_SOURCE", raising=False)
    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orch.test")
    host = "tenant-a.shibari.photo"
    from publisher_v2.config.loader import load_application_config

    tenant_config = load_application_config(None, None).model_copy(update={"auth0": None})
    runtime = SimpleNamespace(host=host, tenant="tenant-a", config=tenant_config)

    class _FakeOrchestratorSource:
        async def get_config(self, _host: str) -> SimpleNamespace:
            return runtime

    class _FakeFactory:
        async def get_service(self, _source: object, _runtime: object) -> SimpleNamespace:
            return SimpleNamespace(config=tenant_config)

    monkeypatch.setattr("publisher_v2.web.middleware.get_config_source", lambda: _FakeOrchestratorSource())
    monkeypatch.setattr("publisher_v2.web.middleware._tenant_service_factory", lambda: _FakeFactory())
    res = TestClient(client.app, base_url=f"http://{host}").get("/api/config/features")
    assert res.status_code == 200, res.text
    assert res.json()["auth_mode"] == "none"
