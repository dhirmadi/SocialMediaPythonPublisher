"""SEC-1 (#76): the pv2_admin cookie must be bound to tenant and host.

A cookie minted on tenant A must not be accepted on tenant B even though every
tenant shares one process and one signing secret in orchestrator mode.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
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
    """Integration-style: same app, two hosts; cookie from host a replayed on host b."""
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("web_admin_pw", "secret")

    app = FastAPI()

    @app.middleware("http")
    async def fake_tenant_middleware(request: Request, call_next):
        host = request.headers.get("host", "")
        request.state.host = host
        request.state.tenant = host.split(".", 1)[0]
        return await call_next(request)

    @app.post("/mutate")
    async def mutate(request: Request) -> dict:
        require_admin(request)
        return {"ok": True}

    cookie = mint_admin_cookie_value(tenant="a", host="a.example.test", mode="password")

    client_a = TestClient(app, base_url="http://a.example.test")
    client_a.cookies.set(ADMIN_COOKIE_NAME, cookie)
    assert client_a.post("/mutate").status_code == 200

    client_b = TestClient(app, base_url="http://b.example.test")
    client_b.cookies.set(ADMIN_COOKIE_NAME, cookie)
    assert client_b.post("/mutate").status_code == 403
