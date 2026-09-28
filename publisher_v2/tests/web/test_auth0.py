from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from publisher_v2.config.schema import Auth0Config
from publisher_v2.web.app import app
from publisher_v2.web.dependencies import get_request_service
from publisher_v2.web.routers.auth import get_auth0_callback_url


@pytest.fixture
def client():
    # Set required env vars for session middleware
    with patch.dict("os.environ", {"WEB_SESSION_SECRET": "test-secret", "WEB_DEBUG": "1"}):
        from publisher_v2.web.app import app

        with TestClient(app) as c:
            yield c


@pytest.fixture
def mock_service():
    with patch("publisher_v2.web.routers.auth.WebImageService") as MockService:
        service_instance = MockService.return_value
        # Default config with Auth0 enabled
        service_instance.config.auth0 = Auth0Config(
            domain="test.auth0.com",
            client_id="test-client-id",
            client_secret="test-client-secret",
            callback_url="http://testserver/auth/callback",
            admin_emails="admin@example.com, user@example.com",
        )
        # Ensure that dependencies using this service get this mocked instance
        with patch("publisher_v2.web.routers.auth.WebImageService", return_value=service_instance):
            yield service_instance


@pytest.fixture
def mock_oauth():
    with patch("publisher_v2.web.routers.auth.oauth") as mock:
        mock._registry = {"auth0": True}
        mock.auth0 = AsyncMock()

        from starlette.responses import RedirectResponse

        mock.auth0.authorize_redirect.return_value = RedirectResponse(
            url="https://test.auth0.com/authorize?foo=bar", status_code=303
        )

        yield mock


@pytest.mark.asyncio
async def test_login_redirect(client, mock_service, mock_oauth):
    mock_service.config.auth0.callback_url = "http://testserver/auth/callback"
    app.dependency_overrides[get_request_service] = lambda request=None: mock_service

    try:
        response = client.get("/auth/login", follow_redirects=False)
        assert response.status_code == 303
        assert "test.auth0.com" in response.headers["location"]
        mock_oauth.auth0.authorize_redirect.assert_called_once()
    finally:
        app.dependency_overrides = {}


def test_login_redirect_no_config(client, mock_service):
    mock_service.config.auth0 = None
    app.dependency_overrides[get_request_service] = lambda request=None: mock_service

    try:
        response = client.get("/auth/login", follow_redirects=False)
        assert response.status_code == 303
        assert "auth_not_configured" in response.headers["location"]
    finally:
        app.dependency_overrides = {}


@pytest.mark.parametrize(
    "email",
    [
        pytest.param("admin@example.com", id="callback_success"),
        pytest.param("ADMIN@EXAMPLE.COM", id="callback_email_case_insensitive"),
    ],
)
@pytest.mark.asyncio
async def test_callback_success(client, mock_service, mock_oauth, email):
    mock_oauth.auth0.authorize_access_token.return_value = {"userinfo": {"email": email, "email_verified": True}}
    app.dependency_overrides[get_request_service] = lambda request=None: mock_service

    try:
        response = client.get("/auth/callback?code=123&state=xyz", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert "pv2_admin" in response.cookies
    finally:
        app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_callback_email_mismatch(client, mock_service, mock_oauth):
    mock_oauth.auth0.authorize_access_token.return_value = {
        "userinfo": {"email": "intruder@example.com", "email_verified": True}
    }
    app.dependency_overrides[get_request_service] = lambda request=None: mock_service

    try:
        response = client.get("/auth/callback?code=123&state=xyz", follow_redirects=False)
        assert response.status_code == 303
        assert "auth_error=access_denied" in response.headers["location"]
        assert "pv2_admin" not in response.cookies
    finally:
        app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_callback_auth0_error(client, mock_service, mock_oauth):
    app.dependency_overrides[get_request_service] = lambda request=None: mock_service

    try:
        response = client.get(
            "/auth/callback?error=access_denied&error_description=User+denied", follow_redirects=False
        )
        assert response.status_code == 303
        assert "auth_error=access_denied" in response.headers["location"]
    finally:
        app.dependency_overrides = {}


def test_logout(client):
    # #91 (SEC-8): logout moved to a CSRF-covered POST; the GET route is gone.
    from publisher_v2.web.auth import mint_admin_cookie_value

    client.cookies.set("pv2_admin", mint_admin_cookie_value(host="testserver"))
    response = client.post("/api/auth/logout", headers={"X-Requested-With": "XMLHttpRequest"})
    assert response.status_code == 200
    assert response.json()["admin"] is False
    assert 'pv2_admin=""' in response.headers.get("set-cookie", "") or "Max-Age=0" in response.headers.get(
        "set-cookie", ""
    )


def test_auth0_config_parsing():
    cfg = Auth0Config(
        domain="d", client_id="i", client_secret="s", callback_url="c", admin_emails="  a@b.com ,  c@d.com,e@f.com  "
    )
    assert cfg.admin_emails_list == ["a@b.com", "c@d.com", "e@f.com"]

    cfg_empty = Auth0Config(domain="d", client_id="i", client_secret="s", callback_url="c", admin_emails="")
    assert cfg_empty.admin_emails_list == []


@pytest.mark.parametrize(
    ("path", "raw_path", "client_ip", "server_host", "server_port", "host_header", "expected"),
    [
        pytest.param(
            "/auth/callback",
            b"/auth/callback",
            "127.0.0.1",
            "localhost",
            8089,
            b"localhost:8089",
            "http://localhost:8089/auth/callback",
            id="get_auth0_callback_url_localhost_preserves_port",
        ),
        pytest.param(
            "/auth/login",
            b"/auth/login",
            "10.0.0.1",
            "staging.example.com",
            443,
            b"staging.example.com",
            "https://staging.example.com/auth/callback",
            id="get_auth0_callback_url_remote_host_forces_https",
        ),
    ],
)
def test_get_auth0_callback_url(path, raw_path, client_ip, server_host, server_port, host_header, expected):
    # Build a Request with localhost + explicit port
    from starlette.requests import Request

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": raw_path,
        "query_string": b"",
        "headers": [(b"host", host_header)],
        "client": (client_ip, 50000),
        "server": (server_host, server_port),
    }
    req = Request(scope)
    assert get_auth0_callback_url(req) == expected


def test_get_auth0_callback_url_without_hostname_returns_none():
    from starlette.requests import Request

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/auth/login",
        "raw_path": b"/auth/login",
        "query_string": b"",
        "headers": [],
        "client": ("10.0.0.1", 50000),
        "server": None,
    }
    req = Request(scope)
    assert get_auth0_callback_url(req) is None
