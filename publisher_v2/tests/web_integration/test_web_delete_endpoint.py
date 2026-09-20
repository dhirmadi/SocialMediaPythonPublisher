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
    monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
    return TestClient(app)


_CSRF = {"X-Requested-With": "XMLHttpRequest"}


def test_delete_requires_admin(client: TestClient) -> None:
    # Without auth credentials, 401 (post-hardening) or 403/404 acceptable.
    res = client.post("/api/images/test.jpg/delete")
    assert res.status_code in (401, 403, 404)


def test_delete_endpoint_success_flow(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Become admin (#137: Auth0 is the only login; Auth0-mode cookie stands in for its callback)
    client.cookies.set(ADMIN_COOKIE_NAME, mint_admin_cookie_value(host="testserver", mode="auth0"))
    assert client.get("/api/admin/status").json()["admin"] is True

    from publisher_v2.web.app import get_service

    svc = get_service()
    # #91 (SEC-11): filename ops validate against the image listing —
    # stub it so no real Dropbox call happens.
    from unittest.mock import AsyncMock as _AsyncMock

    monkeypatch.setattr(svc.storage, "list_images", _AsyncMock(return_value=["test.jpg"]))

    async def _fake_delete(filename: str, *, preview_mode: bool = False, dry_run: bool = False) -> None:
        return None

    monkeypatch.setattr(svc.orchestrator, "delete_image", _fake_delete)
    svc.config.features.delete_enabled = True

    # Browser callers send X-Requested-With via the installed fetch wrapper;
    # the test client must mimic that to satisfy CSRF middleware.
    res = client.post("/api/images/test.jpg/delete", headers=_CSRF)
    assert res.status_code in (200, 404)
