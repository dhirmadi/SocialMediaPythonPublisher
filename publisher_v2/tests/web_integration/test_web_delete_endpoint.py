from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from publisher_v2.web.app import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    cfg = os.environ.get("CONFIG_PATH", "configfiles/fetlife.ini")
    if not os.path.exists(cfg):
        pytest.skip("CONFIG_PATH does not point to a real config; skip web delete integration tests")
    monkeypatch.setenv("CONFIG_PATH", cfg)
    monkeypatch.setenv("web_admin_pw", "secret-admin")
    monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
    return TestClient(app)


def test_delete_requires_admin(client: TestClient) -> None:
    res = client.post("/api/images/test.jpg/delete")
    assert res.status_code in (403, 404)


def test_delete_endpoint_success_flow(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    res = client.post("/api/admin/login", json={"password": "secret-admin"})
    assert res.status_code == 200
    assert client.get("/api/admin/status").json()["admin"] is True

    from publisher_v2.web.app import get_service

    svc = get_service()

    async def _fake_delete(filename: str, *, preview_mode: bool = False, dry_run: bool = False) -> None:
        return None

    monkeypatch.setattr(svc.orchestrator, "delete_image", _fake_delete)
    svc.config.features.delete_enabled = True

    res = client.post("/api/images/test.jpg/delete")
    assert res.status_code in (200, 404)
