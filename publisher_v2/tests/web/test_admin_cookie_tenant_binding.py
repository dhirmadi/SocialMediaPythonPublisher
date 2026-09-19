"""SEC-1 (#76): the pv2_admin cookie must be bound to tenant and host.

A cookie minted on tenant A must not be accepted on tenant B even though every
tenant shares one process and one signing secret in orchestrator mode.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from publisher_v2.web.auth import (
    ADMIN_COOKIE_NAME,
    _serializer,
    is_admin_request,
    mint_admin_cookie_value,
    require_admin,
)


def _request_with_state(
    cookie: str | None,
    *,
    tenant: str | None = None,
    host: str | None = None,
    header_host: str = "testserver",
    config: object | None = None,
) -> Request:
    """Build a real starlette Request carrying cookie + orchestrator state."""
    headers = [(b"host", header_host.encode())]
    if cookie is not None:
        headers.append((b"cookie", f"{ADMIN_COOKIE_NAME}={cookie}".encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "query_string": b"",
    }
    request = Request(scope)
    if tenant is not None:
        request.state.tenant = tenant
    if host is not None:
        request.state.host = host
    if config is not None:
        request.state.config = config
    return request


def test_cookie_minted_for_tenant_a_rejected_on_tenant_b(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    cookie = mint_admin_cookie_value(tenant="a", host="a.example.test", mode="password")
    request = _request_with_state(cookie, tenant="b", host="b.example.test")
    assert is_admin_request(request) is False


def test_cookie_minted_for_tenant_a_accepted_on_tenant_a(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    cookie = mint_admin_cookie_value(tenant="a", host="a.example.test", mode="password")
    request = _request_with_state(cookie, tenant="a", host="a.example.test")
    assert is_admin_request(request) is True


def test_legacy_cookie_without_tenant_claim_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    # Pre-#76 cookies carried only a session id.
    legacy = _serializer().dumps({"sid": "legacy-session"})
    request = _request_with_state(legacy, tenant="a", host="a.example.test")
    assert is_admin_request(request) is False


def test_standalone_mode_binds_to_host_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    cookie = mint_admin_cookie_value(host="testserver")
    assert is_admin_request(_request_with_state(cookie, header_host="testserver")) is True
    assert is_admin_request(_request_with_state(cookie, header_host="evil.example")) is False


def test_require_admin_403_when_tenant_auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tenant policy with Auth0 disabled (auth0=None) and no password login → 403 despite valid cookie."""
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    monkeypatch.delenv("web_admin_pw", raising=False)
    monkeypatch.delenv("AUTH0_DOMAIN", raising=False)
    monkeypatch.delenv("AUTH0_CLIENT_ID", raising=False)
    cookie = mint_admin_cookie_value(tenant="a", host="a.example.test", mode="auth0")
    tenant_config = SimpleNamespace(auth0=None)
    request = _request_with_state(cookie, tenant="a", host="a.example.test", config=tenant_config)
    with pytest.raises(HTTPException) as exc_info:
        require_admin(request)
    assert exc_info.value.status_code == 403


def test_cross_tenant_replay_returns_403_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real app, real chain (Session -> CSRF -> tenant_middleware -> require_admin).

    #135: previously a fake FastAPI app with a fake tenant middleware. Now only the
    orchestrator config source (external service) and the tenant service factory
    are stubbed; the real tenant_middleware sets request.state.tenant/host from the
    Host header, and a cookie minted for tenant a is replayed against tenant b.
    """
    from publisher_v2.web.app import app

    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orch.test")
    monkeypatch.delenv("CONFIG_SOURCE", raising=False)

    def _tenant_config() -> SimpleNamespace:
        return SimpleNamespace(
            auth0=SimpleNamespace(domain="t.auth0.com"),
            content=SimpleNamespace(voice_profile=None),
            features=SimpleNamespace(voice_matching_enabled=False),
        )

    class _FakeOrchestratorSource:
        async def get_config(self, host: str) -> SimpleNamespace:
            return SimpleNamespace(host=host, tenant=host.split(".", 1)[0], config=_tenant_config())

    class _FakeFactory:
        async def get_service(self, _source: object, runtime: SimpleNamespace) -> SimpleNamespace:
            return SimpleNamespace(config=runtime.config)

    monkeypatch.setattr("publisher_v2.web.middleware.get_config_source", lambda: _FakeOrchestratorSource())
    monkeypatch.setattr("publisher_v2.web.middleware._tenant_service_factory", lambda: _FakeFactory())

    cookie = mint_admin_cookie_value(tenant="a", host="a.example.test", mode="auth0")

    client_a = TestClient(app, base_url="http://a.example.test")
    client_a.cookies.set(ADMIN_COOKIE_NAME, cookie)
    assert client_a.get("/api/config/voice-profile").status_code == 200

    client_b = TestClient(app, base_url="http://b.example.test")
    client_b.cookies.set(ADMIN_COOKIE_NAME, cookie)
    res = client_b.get("/api/config/voice-profile")
    assert res.status_code == 403
    assert res.json()["detail"] == "Admin privileges required"
