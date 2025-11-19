from __future__ import annotations

import base64
from typing import Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from publisher_v2.web.auth import require_auth


def _make_app(env: Dict[str, str]) -> TestClient:
    app = FastAPI()

    @app.get("/protected")
    async def protected() -> dict:
        await require_auth(app.state.request)  # type: ignore[attr-defined]
        return {"ok": True}

    # FastAPI dependency injection does not give us the raw Request easily for this
    # tiny test, so we attach it to app.state in a simple middleware.
    @app.middleware("http")
    async def store_request(request, call_next):  # type: ignore[no-untyped-def]
        app.state.request = request
        return await call_next(request)

    # Patch env for this client only: clear relevant keys then set provided ones
    import os

    for key in ("WEB_AUTH_TOKEN", "WEB_AUTH_USER", "WEB_AUTH_PASS"):
        os.environ.pop(key, None)
    for k, v in env.items():
        os.environ[k] = v

    return TestClient(app)


def test_require_auth_bearer_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_app({"WEB_AUTH_TOKEN": "secret-token"})
    res = client.get("/protected", headers={"Authorization": "Bearer secret-token"})
    assert res.status_code == 200


def test_require_auth_bearer_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_app({"WEB_AUTH_TOKEN": "secret-token"})
    res = client.get("/protected", headers={"Authorization": "Bearer wrong"})
    assert res.status_code == 401


def test_require_auth_basic_success(monkeypatch: pytest.MonkeyPatch) -> None:
    token = base64.b64encode(b"user:pass").decode("ascii")
    client = _make_app({"WEB_AUTH_USER": "user", "WEB_AUTH_PASS": "pass"})
    res = client.get("/protected", headers={"Authorization": f"Basic {token}"})
    assert res.status_code == 200


def test_require_auth_disabled_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_app({})
    res = client.get("/protected")
    # When auth is disabled, endpoint should allow access
    assert res.status_code == 200



