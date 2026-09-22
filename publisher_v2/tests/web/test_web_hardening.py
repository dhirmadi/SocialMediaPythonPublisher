"""SEC-8 (#91 item B): CSP nonce, HSTS, POST logout, PKCE."""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
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
        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.setenv("AUTH0_CLIENT_ID", "cid")
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
        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.setenv("AUTH0_CLIENT_ID", "cid")
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


class TestFilenameAllowList:
    """SEC-11 (#91 D): only listed image names may reach storage operations."""

    def _service(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        from unittest.mock import AsyncMock

        # #97 stage 4: env-only configuration (INI removed)
        monkeypatch.setenv("STORAGE_PATHS", '{"root": "/Photos", "archive": "archive"}')
        monkeypatch.setenv("PUBLISHERS", "[]")
        monkeypatch.setenv("OPENAI_SETTINGS", "{}")
        monkeypatch.setenv("DROPBOX_APP_KEY", "k")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "s")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "r")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.web.service import WebImageService

            service = WebImageService()
        service.storage.list_images = AsyncMock(return_value=["real.jpg"])  # type: ignore[method-assign]
        service.storage.get_temporary_link = AsyncMock(return_value="http://temp")  # type: ignore[method-assign]
        service.storage.download_sidecar_if_exists = AsyncMock(return_value=None)  # type: ignore[method-assign]
        return service

    async def test_sidecar_txt_name_rejected(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        service = self._service(monkeypatch, tmp_path)
        with pytest.raises(FileNotFoundError):
            await service.get_image_details("real.txt")

    async def test_traversal_name_rejected(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        service = self._service(monkeypatch, tmp_path)
        with pytest.raises(FileNotFoundError):
            await service.analyze_and_caption("../../etc/passwd.jpg")

    async def test_unlisted_image_rejected_listed_allowed(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        service = self._service(monkeypatch, tmp_path)
        with pytest.raises(FileNotFoundError):
            await service.get_image_details("other.jpg")
        result = await service.get_image_details("real.jpg")
        assert result.filename == "real.jpg"

    async def test_curation_paths_gated(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        service = self._service(monkeypatch, tmp_path)
        with pytest.raises(FileNotFoundError):
            await service.keep_image("../real.jpg")
        with pytest.raises(FileNotFoundError):
            await service.remove_image("nope.jpg")
        with pytest.raises(FileNotFoundError):
            await service.delete_image("real.txt")


class TestHeaderAuthWithCookie:
    """SEC-3 (#91 A, decision b): cookie-alone default; strict opt-in flag."""

    def _app(self):
        from publisher_v2.web.auth import require_auth

        app = FastAPI()

        @app.post("/mutate")
        async def mutate(request: Request) -> dict:
            await require_auth(request)
            return {"ok": True}

        return TestClient(app)

    def _cookie(self) -> str:
        from publisher_v2.web.auth import mint_admin_cookie_value

        return mint_admin_cookie_value(host="testserver")

    def test_default_cookie_alone_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
        monkeypatch.setenv("WEB_AUTH_TOKEN", "token-1")
        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.setenv("AUTH0_CLIENT_ID", "cid")
        monkeypatch.delenv("WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE", raising=False)
        client = self._app()
        client.cookies.set("pv2_admin", self._cookie())
        assert client.post("/mutate").status_code == 200

    def test_strict_mode_rejects_cookie_alone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
        monkeypatch.setenv("WEB_AUTH_TOKEN", "token-1")
        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.setenv("AUTH0_CLIENT_ID", "cid")
        monkeypatch.setenv("WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE", "1")
        client = self._app()
        client.cookies.set("pv2_admin", self._cookie())
        assert client.post("/mutate").status_code == 401

    def test_strict_mode_accepts_header_plus_cookie(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
        monkeypatch.setenv("WEB_AUTH_TOKEN", "token-1")
        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.setenv("AUTH0_CLIENT_ID", "cid")
        monkeypatch.setenv("WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE", "1")
        client = self._app()
        client.cookies.set("pv2_admin", self._cookie())
        res = client.post("/mutate", headers={"Authorization": "Bearer token-1"})
        assert res.status_code == 200


class TestOpenApiDisabled:
    """PUB-048 AC5 (#187): the schema and its viewers are not served anonymously."""

    def test_docs_redoc_openapi_json_all_404_for_anonymous_request(self, client: TestClient) -> None:
        statuses = {
            path: client.get(path, follow_redirects=False).status_code for path in ("/docs", "/redoc", "/openapi.json")
        }

        assert statuses == {"/docs": 404, "/redoc": 404, "/openapi.json": 404}, (
            f"the route table and upload contract are still readable anonymously: {statuses}"
        )
