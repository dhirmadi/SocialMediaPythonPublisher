from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from publisher_v2.web.app import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Ensure CONFIG_PATH exists; if not, skip tests.
    cfg = os.environ.get("CONFIG_PATH", "configfiles/fetlife.ini")
    if not os.path.exists(cfg):
        pytest.skip("CONFIG_PATH does not point to a real config; skip web admin integration tests")
    monkeypatch.setenv("CONFIG_PATH", cfg)
    monkeypatch.setenv("web_admin_pw", "secret-admin")
    # Disable secure cookies for test client (uses HTTP, not HTTPS)
    monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
    # For admin tests we do not require WEB_AUTH_TOKEN to be set; if it is,
    # callers should provide it, but here we focus on admin cookie behavior.
    return TestClient(app)


def test_admin_login_success(client: TestClient) -> None:
    res = client.post("/api/admin/login", json={"password": "secret-admin"})
    assert res.status_code == 200
    data = res.json()
    assert data["admin"] is True
    # Cookie should be set
    assert "pv2_admin" in client.cookies


def test_admin_login_failure(client: TestClient) -> None:
    res = client.post("/api/admin/login", json={"password": "wrong"})
    assert res.status_code == 401


def test_admin_status_and_cookie_flow(client: TestClient) -> None:
    # Initially not admin
    res = client.get("/api/admin/status")
    assert res.status_code == 200
    assert res.json()["admin"] is False

    # Login to become admin
    res = client.post("/api/admin/login", json={"password": "secret-admin"})
    assert res.status_code == 200

    # Now status should report admin=true
    res = client.get("/api/admin/status")
    assert res.status_code == 200
    assert res.json()["admin"] is True


def test_admin_logout_clears_cookie(client: TestClient) -> None:
    # Login to become admin
    res = client.post("/api/admin/login", json={"password": "secret-admin"})
    assert res.status_code == 200
    assert client.get("/api/admin/status").json()["admin"] is True

    # Logout should clear admin status
    res = client.post("/api/admin/logout")
    assert res.status_code == 200
    assert client.get("/api/admin/status").json()["admin"] is False


def test_analyze_publish_require_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = os.environ.get("CONFIG_PATH", "configfiles/fetlife.ini")
    if not os.path.exists(cfg):
        pytest.skip("CONFIG_PATH does not point to a real config; skip web admin integration tests")
    monkeypatch.setenv("CONFIG_PATH", cfg)
    monkeypatch.setenv("web_admin_pw", "secret-admin")
    client = TestClient(app)

    # Without admin cookie, should be 403 or 404 depending on image existence
    res = client.post("/api/images/test.jpg/analyze")
    assert res.status_code in (403, 404)

    res = client.post("/api/images/test.jpg/publish")
    assert res.status_code in (403, 404)


