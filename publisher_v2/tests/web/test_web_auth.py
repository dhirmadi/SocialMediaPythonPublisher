from __future__ import annotations

import base64

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from publisher_v2.web.auth import require_auth


def _make_app(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> TestClient:
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

    # Patch env for this test only (#135: via monkeypatch, so nothing leaks).
    for key in ("WEB_AUTH_TOKEN", "WEB_AUTH_USER", "WEB_AUTH_PASS"):
        monkeypatch.delenv(key, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    return TestClient(app)


def test_require_auth_bearer_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_app({"WEB_AUTH_TOKEN": "secret-token"}, monkeypatch)
    res = client.get("/protected", headers={"Authorization": "Bearer secret-token"})
    assert res.status_code == 200


def test_require_auth_bearer_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_app({"WEB_AUTH_TOKEN": "secret-token"}, monkeypatch)
    res = client.get("/protected", headers={"Authorization": "Bearer wrong"})
    assert res.status_code == 401


def test_require_auth_basic_success(monkeypatch: pytest.MonkeyPatch) -> None:
    token = base64.b64encode(b"user:pass").decode("ascii")
    client = _make_app({"WEB_AUTH_USER": "user", "WEB_AUTH_PASS": "pass"}, monkeypatch)
    res = client.get("/protected", headers={"Authorization": f"Basic {token}"})
    assert res.status_code == 200


def test_require_auth_fails_closed_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Post-hardening: missing auth backend must NOT silently allow mutating
    requests. Operators must opt in explicitly via WEB_ALLOW_UNAUTHENTICATED."""
    for key in ("WEB_ALLOW_UNAUTHENTICATED", "AUTH0_DOMAIN", "AUTH0_CLIENT_ID"):
        monkeypatch.delenv(key, raising=False)
    client = _make_app({}, monkeypatch)
    res = client.get("/protected")
    assert res.status_code == 503


def test_require_auth_explicit_dev_optout(monkeypatch: pytest.MonkeyPatch) -> None:
    """WEB_ALLOW_UNAUTHENTICATED=1 is the documented dev escape hatch."""
    monkeypatch.setenv("WEB_ALLOW_UNAUTHENTICATED", "1")
    client = _make_app({}, monkeypatch)
    res = client.get("/protected")
    assert res.status_code == 200


class TestNonAsciiCredentials:
    """SEC-9 (#87): non-ASCII credentials must yield 401, not a TypeError 500."""

    def test_non_ascii_bearer_returns_401(self, monkeypatch) -> None:
        import base64

        from publisher_v2.web.auth import require_auth

        monkeypatch.setenv("WEB_AUTH_TOKEN", "secret-token")
        app = FastAPI()

        @app.get("/guarded")
        async def guarded(request: Request) -> dict:
            await require_auth(request)
            return {"ok": True}

        client = TestClient(app)
        res = client.get("/guarded", headers={b"Authorization": "Bearer é-token".encode("latin-1")})
        assert res.status_code == 401, res.text

        monkeypatch.delenv("WEB_AUTH_TOKEN")
        monkeypatch.setenv("WEB_AUTH_USER", "user")
        monkeypatch.setenv("WEB_AUTH_PASS", "pass")
        creds = base64.b64encode("usér:pâss".encode()).decode()
        res = client.get("/guarded", headers={"Authorization": f"Basic {creds}"})
        assert res.status_code == 401
