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
