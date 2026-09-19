from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from publisher_v2.web.auth import (
    ADMIN_COOKIE_NAME,
    mint_admin_cookie_value,
    require_admin,
    verify_admin_password,
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
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    app = FastAPI()

    @app.get("/protected")
    async def protected(request: Request) -> dict:
        require_admin(request)
        return {"ok": True}

    client = TestClient(app)
    # Mint a valid signed cookie — plain "1" is no longer accepted post-hardening.
    client.cookies.set(ADMIN_COOKIE_NAME, mint_admin_cookie_value(host="testserver"))
    res = client.get("/protected")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_require_admin_rejects_tampered_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("web_admin_pw", "secret")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    client = _make_app_for_admin()
    client.cookies.set(ADMIN_COOKIE_NAME, "1")  # not a valid signed payload
    res = client.get("/protected")
    assert res.status_code == 403


class TestDevSecretOptIn:
    """SEC-5 (#87): WEB_DEBUG alone must not enable the public dev secret."""

    def test_web_debug_alone_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from publisher_v2.web.auth import _cookie_secret

        monkeypatch.delenv("WEB_SESSION_SECRET", raising=False)
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.delenv("WEB_DEV_INSECURE_SECRET", raising=False)
        monkeypatch.setenv("WEB_DEBUG", "1")
        with pytest.raises(RuntimeError):
            _cookie_secret()

    def test_explicit_insecure_flag_enables_dev_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from publisher_v2.web.auth import _cookie_secret

        monkeypatch.delenv("WEB_SESSION_SECRET", raising=False)
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.setenv("WEB_DEV_INSECURE_SECRET", "1")
        assert _cookie_secret() == "dev_secret_do_not_use_in_prod"
