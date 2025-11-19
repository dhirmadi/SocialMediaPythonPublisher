from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from publisher_v2.web.auth import (
    ADMIN_COOKIE_NAME,
    verify_admin_password,
    require_admin,
)


def test_verify_admin_password_matches() -> None:
    assert verify_admin_password("secret", "secret") is True


def test_verify_admin_password_mismatch() -> None:
    assert verify_admin_password("secret", "other") is False


def _make_app_for_admin() -> TestClient:
    app = FastAPI()

    @app.get("/protected")
    async def protected(request: Request) -> dict:
        require_admin(request)
        return {"ok": True}

    return TestClient(app)


def test_require_admin_rejects_without_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure admin is considered configured so require_admin checks cookie
    monkeypatch.setenv("web_admin_pw", "secret")
    client = _make_app_for_admin()
    res = client.get("/protected")
    assert res.status_code == 403


def test_require_admin_accepts_with_valid_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("web_admin_pw", "secret")
    app = FastAPI()

    @app.get("/protected")
    async def protected(request: Request) -> dict:
        require_admin(request)
        return {"ok": True}

    client = TestClient(app)
    # Manually set the admin cookie on the client
    client.cookies.set(ADMIN_COOKIE_NAME, "1")
    res = client.get("/protected")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


