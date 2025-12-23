from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from publisher_v2.web.app import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    cfg = os.environ.get("CONFIG_PATH", "configfiles/fetlife.ini")
    if not os.path.exists(cfg):
        pytest.skip("CONFIG_PATH does not point to a real config; skip web keep/remove integration tests")
    monkeypatch.setenv("CONFIG_PATH", cfg)
    monkeypatch.setenv("web_admin_pw", "secret-admin")
    # Disable secure cookies for test client (uses HTTP, not HTTPS)
    monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
    return TestClient(app)


def test_keep_remove_require_admin(client: TestClient) -> None:
    # Without admin cookie, endpoints must be protected (403/404 depending on image existence).
    res = client.post("/api/images/test.jpg/keep")
    assert res.status_code in (403, 404)

    res = client.post("/api/images/test.jpg/remove")
    assert res.status_code in (403, 404)


def test_keep_remove_endpoint_success_flow(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Login to become admin
    res = client.post("/api/admin/login", json={"password": "secret-admin"})
    assert res.status_code == 200
    assert client.get("/api/admin/status").json()["admin"] is True

    # Mock orchestrator methods to avoid real Dropbox calls
    from publisher_v2.web.app import get_service

    svc = get_service()

    async def _fake_keep(filename: str, *, preview_mode: bool = False, dry_run: bool = False) -> None:
        return None

    async def _fake_remove(filename: str, *, preview_mode: bool = False, dry_run: bool = False) -> None:
        return None

    monkeypatch.setattr(svc.orchestrator, "keep_image", _fake_keep)
    monkeypatch.setattr(svc.orchestrator, "remove_image", _fake_remove)
    svc.config.features.keep_enabled = True
    svc.config.features.remove_enabled = True

    # Keep
    res = client.post("/api/images/test.jpg/keep")
    # When the test image does not exist, implementation may return 404; we only assert no auth error here.
    assert res.status_code in (200, 404)

    # Remove
    res = client.post("/api/images/test.jpg/remove")
    assert res.status_code in (200, 404)


