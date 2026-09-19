"""SEC-8 (#91 item B): CSP nonce, HSTS, POST logout, PKCE."""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Import first: publisher_v2.web.service runs load_dotenv() once per
    # process, which can re-introduce workspace env after a delenv.
    from publisher_v2.web.app import app

    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)
    monkeypatch.setenv("CONFIG_SOURCE", "env")
    return TestClient(app)


class TestCspNonce:
    def test_script_src_uses_nonce_not_unsafe_inline(self, client: TestClient) -> None:
        res = client.get("/")
        csp = res.headers["content-security-policy"]
        script_src = next(part for part in csp.split(";") if part.strip().startswith("script-src"))
        assert "'unsafe-inline'" not in script_src
        assert "'nonce-" in script_src

    def test_inline_script_carries_matching_nonce(self, client: TestClient) -> None:
        res = client.get("/")
        csp = res.headers["content-security-policy"]
        match = re.search(r"'nonce-([A-Za-z0-9_-]+)'", csp)
        assert match, csp
        assert f'nonce="{match.group(1)}"' in res.text

    def test_nonce_changes_per_request(self, client: TestClient) -> None:
        n1 = re.search(r"'nonce-([A-Za-z0-9_-]+)'", client.get("/").headers["content-security-policy"])
        n2 = re.search(r"'nonce-([A-Za-z0-9_-]+)'", client.get("/").headers["content-security-policy"])
        assert n1 and n2 and n1.group(1) != n2.group(1)


class TestHsts:
    def test_hsts_present_when_secure_cookies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from publisher_v2.web.app import app

        monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
        monkeypatch.setenv("WEB_SECURE_COOKIES", "true")
        monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)
        res = TestClient(app).get("/health")
        assert res.headers.get("strict-transport-security") == "max-age=31536000; includeSubDomains"

    def test_hsts_absent_when_insecure_dev(self, client: TestClient) -> None:
        res = client.get("/health")
        assert "strict-transport-security" not in res.headers


class TestPostLogout:
    def test_post_api_auth_logout_clears_admin(self, monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
        monkeypatch.setenv("web_admin_pw", "secret")
        from publisher_v2.web.auth import mint_admin_cookie_value

        client.cookies.set("pv2_admin", mint_admin_cookie_value(host="testserver"))
        res = client.post("/api/auth/logout", headers={"X-Requested-With": "XMLHttpRequest"})
        assert res.status_code == 200
        assert res.json()["admin"] is False

    def test_get_auth_logout_gone(self, client: TestClient) -> None:
        res = client.get("/auth/logout", follow_redirects=False)
        assert res.status_code in (404, 405)


class TestPkce:
    def test_oauth_registered_with_s256(self) -> None:
        from types import SimpleNamespace

        from publisher_v2.web.routers import auth as auth_router

        captured: dict = {}

        def _register(name: str, **kwargs) -> None:
            captured.update(kwargs)

        config = SimpleNamespace(auth0=SimpleNamespace(client_id="cid", client_secret="cs", domain="tenant.auth0.test"))
        with patch.object(auth_router.oauth, "register", side_effect=_register):
            auth_router.configure_oauth(config)

        assert captured["client_kwargs"]["code_challenge_method"] == "S256"


class TestCookieRevocation:
    """SEC-10 (#91 C): logout revokes the sid; epoch rotates all cookies."""

    def test_logout_revokes_the_presented_cookie(self, monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
        monkeypatch.setenv("web_admin_pw", "secret")
        from publisher_v2.web.auth import mint_admin_cookie_value

        cookie = mint_admin_cookie_value(host="testserver")
        client.cookies.set("pv2_admin", cookie)
        assert client.get("/api/admin/status").json()["admin"] is True

        res = client.post("/api/auth/logout", headers={"X-Requested-With": "XMLHttpRequest"})
        assert res.status_code == 200

        # Replaying the same signed cookie after logout must fail.
        client.cookies.set("pv2_admin", cookie)
        assert client.get("/api/admin/status").json()["admin"] is False

    def test_epoch_rotation_invalidates_existing_cookies(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from starlette.requests import Request as StarletteRequest

        from publisher_v2.web.auth import ADMIN_COOKIE_NAME, is_admin_request, mint_admin_cookie_value

        monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
        monkeypatch.setenv("WEB_ADMIN_COOKIE_EPOCH", "1")
        cookie = mint_admin_cookie_value(host="testserver")

        def _req(value: str) -> StarletteRequest:
            return StarletteRequest(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/",
                    "headers": [(b"host", b"testserver"), (b"cookie", f"{ADMIN_COOKIE_NAME}={value}".encode())],
                    "query_string": b"",
                }
            )

        assert is_admin_request(_req(cookie)) is True
        monkeypatch.setenv("WEB_ADMIN_COOKIE_EPOCH", "2")
        assert is_admin_request(_req(cookie)) is False


class TestRateLimiterKeyCap:
    def test_new_key_refused_when_capacity_reached(self) -> None:
        from fastapi import HTTPException as FastapiHTTPException

        from publisher_v2.web.rate_limit import SlidingWindowLimiter

        limiter = SlidingWindowLimiter(window_seconds=60, max_events=5, label="cap-test")
        limiter._max_keys = 2
        limiter.check("a")
        limiter.check("b")
        with pytest.raises(FastapiHTTPException) as exc_info:
            limiter.check("c")
        assert exc_info.value.status_code == 429

    def test_library_rate_dicts_pruned_on_check(self) -> None:
        import time as _time

        from starlette.requests import Request as StarletteRequest

        from publisher_v2.web.routers import library

        library._upload_rate_limit.clear()
        library._upload_rate_limit["stale-cookie"] = [_time.time() - 3600]
        request = StarletteRequest(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/library/upload",
                "headers": [(b"cookie", b"pv2_admin=fresh")],
                "query_string": b"",
            }
        )
        library._check_rate_limit(request)
        assert "stale-cookie" not in library._upload_rate_limit
        library._upload_rate_limit.clear()
