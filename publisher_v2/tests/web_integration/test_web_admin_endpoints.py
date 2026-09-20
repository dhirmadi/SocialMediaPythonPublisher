from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from publisher_v2.web.app import app
from publisher_v2.web.auth import ADMIN_COOKIE_NAME, mint_admin_cookie_value


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, env_first_config: None) -> TestClient:
    # #137: Auth0 is the only admin login; there is no password to set.
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    monkeypatch.setenv("AUTH0_CLIENT_ID", "cid")
    monkeypatch.setenv("AUTH0_CLIENT_SECRET", "sec")
    # Disable secure cookies for test client (uses HTTP, not HTTPS)
    monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
    # For admin tests we do not require WEB_AUTH_TOKEN to be set; if it is,
    # callers should provide it, but here we focus on admin cookie behavior.
    return TestClient(app)


def _become_admin(client: TestClient) -> None:
    """#137: Auth0 is the only login; stand in for its callback with an Auth0-mode cookie."""
    client.cookies.set(ADMIN_COOKIE_NAME, mint_admin_cookie_value(host="testserver", mode="auth0"))


def test_admin_status_and_cookie_flow(client: TestClient) -> None:
    # Initially not admin
    res = client.get("/api/admin/status")
    assert res.status_code == 200
    assert res.json()["admin"] is False

    # Become admin (Auth0 callback stand-in)
    _become_admin(client)

    # Now status should report admin=true
    res = client.get("/api/admin/status")
    assert res.status_code == 200
    assert res.json()["admin"] is True


def test_admin_logout_clears_cookie(client: TestClient) -> None:
    _become_admin(client)
    assert client.get("/api/admin/status").json()["admin"] is True

    # Logout (state-changing POST) — browser callers carry X-Requested-With
    # via the installed fetch wrapper; test client must mimic that to satisfy
    # the CSRF middleware.
    res = client.post("/api/admin/logout", headers={"X-Requested-With": "XMLHttpRequest"})
    assert res.status_code == 200
    assert client.get("/api/admin/status").json()["admin"] is False


def test_admin_logout_without_csrf_header_is_blocked(client: TestClient) -> None:
    """POSTing logout from a cross-origin form (no X-Requested-With) is blocked."""
    _become_admin(client)
    res = client.post("/api/admin/logout")  # no CSRF header
    assert res.status_code == 403


def test_analyze_publish_require_admin(monkeypatch: pytest.MonkeyPatch, env_first_config: None) -> None:
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    monkeypatch.setenv("AUTH0_CLIENT_ID", "cid")
    monkeypatch.setenv("AUTH0_CLIENT_SECRET", "sec")
    client = TestClient(app)

    # Without admin cookie, should be blocked. Post-hardening returns 401
    # (no credentials) rather than 403 (forbidden); both indicate the route
    # is properly gated.
    res = client.post("/api/images/test.jpg/analyze")
    assert res.status_code in (401, 403, 404)

    res = client.post("/api/images/test.jpg/publish")
    assert res.status_code in (401, 403, 404)
