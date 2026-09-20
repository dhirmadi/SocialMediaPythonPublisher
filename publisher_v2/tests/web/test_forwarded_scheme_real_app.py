"""#129: forwarded scheme through the real app behind uvicorn's proxy middleware.

Heroku's router is not loopback, so uvicorn's ``ProxyHeadersMiddleware`` with
the default ``FORWARDED_ALLOW_IPS=127.0.0.1`` leaves ``request.url.scheme`` as
``http``. The browser sends ``Origin: https://<host>``. With
``WEB_TRUST_FORWARDED_FOR=true`` the app must derive the scheme from
``X-Forwarded-Proto`` itself, both for CSRF same-origin checks and for the
Auth0 callback URL.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from starlette.requests import Request
from starlette.responses import RedirectResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from publisher_v2.config.schema import Auth0Config
from publisher_v2.web.app import app
from publisher_v2.web.dependencies import get_request_service
from publisher_v2.web.rate_limit import request_scheme

HEROKU_ROUTER_PEER = ("10.1.2.3", 40000)


def _wrapped() -> ProxyHeadersMiddleware:
    # Production default: FORWARDED_ALLOW_IPS unset -> only loopback trusted.
    return ProxyHeadersMiddleware(app, trusted_hosts="127.0.0.1")


async def _logout(proto: str = "https", origin: str = "https://testserver") -> httpx.Response:
    transport = httpx.ASGITransport(app=_wrapped(), client=HEROKU_ROUTER_PEER)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(
            "/api/auth/logout",
            headers={
                "X-Forwarded-Proto": proto,
                "Origin": origin,
                "X-Requested-With": "XMLHttpRequest",
                "Cookie": "pv2_admin=anything",
            },
        )


@pytest.mark.asyncio
async def test_logout_behind_proxy_with_trust_flag_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_TRUST_FORWARDED_FOR", "true")
    res = await _logout()
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_logout_behind_proxy_without_trust_flag_returns_403(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEB_TRUST_FORWARDED_FOR", raising=False)
    res = await _logout()
    assert res.status_code == 403
    assert res.json() == {"detail": "CSRF check failed"}


@pytest.mark.asyncio
async def test_trusted_forwarded_proto_does_not_admit_cross_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_TRUST_FORWARDED_FOR", "true")
    res = await _logout(origin="https://evil.example")
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_garbage_forwarded_proto_falls_back_to_request_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only http/https are honoured; anything else falls back to request.url.scheme (http)."""
    monkeypatch.setenv("WEB_TRUST_FORWARDED_FOR", "true")
    assert (await _logout(proto="javascript")).status_code == 403
    assert (await _logout(proto="javascript", origin="http://testserver")).status_code == 200


@pytest.mark.asyncio
async def test_forwarded_proto_is_lowercased(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_TRUST_FORWARDED_FOR", "true")
    assert (await _logout(proto="HTTPS")).status_code == 200


@pytest.mark.asyncio
async def test_disagreeing_forwarded_proto_values_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A client's forged `https` plus a proxy's appended `http` must not be honoured.

    The issue asked for "the first value"; taking it would let a client assert
    `https` on a plain-http hop behind any appending proxy. Deviation recorded
    in the PR body.
    """
    monkeypatch.setenv("WEB_TRUST_FORWARDED_FOR", "true")
    assert (await _logout(proto="https, http")).status_code == 403


@pytest.mark.asyncio
async def test_agreeing_forwarded_proto_values_are_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cloudflare in Full mode in front of Heroku produces `https, https`.

    Refusing every multi-valued header would bring the 403 back in exactly the
    deployment CONFIGURATION.md §10.2 tells operators to move to.
    """
    monkeypatch.setenv("WEB_TRUST_FORWARDED_FOR", "true")
    assert (await _logout(proto="https, https")).status_code == 200


@pytest.fixture
def auth0_service() -> Iterator[AsyncMock]:
    """Service stub carrying Auth0 config; the IdP client (oauth.auth0) is faked at its boundary."""
    service = AsyncMock()
    service.config.auth0 = Auth0Config(
        domain="test.auth0.com",
        client_id="cid",
        client_secret="secret",
        callback_url=None,
        admin_emails="admin@example.com",
    )
    app.dependency_overrides[get_request_service] = lambda: service
    with patch("publisher_v2.web.routers.auth.oauth") as oauth:
        oauth._registry = {"auth0": True}
        oauth.auth0 = AsyncMock()
        oauth.auth0.authorize_redirect.return_value = RedirectResponse(
            url="https://test.auth0.com/authorize", status_code=303
        )
        yield oauth
    app.dependency_overrides.pop(get_request_service, None)


async def _login_redirect_uri(oauth: AsyncMock, host: str, proto: str) -> str:
    transport = httpx.ASGITransport(app=_wrapped(), client=HEROKU_ROUTER_PEER)
    async with httpx.AsyncClient(transport=transport, base_url=f"http://{host}") as client:
        res = await client.get("/auth/login", headers={"X-Forwarded-Proto": proto}, follow_redirects=False)
    assert res.status_code == 303, res.text
    return oauth.auth0.authorize_redirect.call_args.args[1]


@pytest.mark.asyncio
async def test_auth0_callback_public_host_with_trust_flag_is_https(
    monkeypatch: pytest.MonkeyPatch, auth0_service: AsyncMock
) -> None:
    """Pins the public-host https floor with the flag on; the helper is proven by the localhost tests."""
    monkeypatch.setenv("WEB_TRUST_FORWARDED_FOR", "true")
    uri = await _login_redirect_uri(auth0_service, "tenant.example.com", "https")
    assert uri == "https://tenant.example.com/auth/callback"


@pytest.mark.asyncio
async def test_auth0_callback_localhost_behind_proxy_with_trust_flag_uses_forwarded_scheme(
    monkeypatch: pytest.MonkeyPatch, auth0_service: AsyncMock
) -> None:
    """Localhost keeps its port; the scheme now comes from the trusted forwarded header."""
    monkeypatch.setenv("WEB_TRUST_FORWARDED_FOR", "true")
    uri = await _login_redirect_uri(auth0_service, "localhost:8089", "https")
    assert uri == "https://localhost:8089/auth/callback"


@pytest.mark.asyncio
async def test_auth0_callback_localhost_behind_proxy_without_trust_flag_ignores_forwarded_scheme(
    monkeypatch: pytest.MonkeyPatch, auth0_service: AsyncMock
) -> None:
    monkeypatch.delenv("WEB_TRUST_FORWARDED_FOR", raising=False)
    uri = await _login_redirect_uri(auth0_service, "localhost:8089", "https")
    assert uri == "http://localhost:8089/auth/callback"


@pytest.mark.asyncio
async def test_auth0_callback_public_host_without_trust_flag_stays_https(
    monkeypatch: pytest.MonkeyPatch, auth0_service: AsyncMock
) -> None:
    """Public hosts never get an http callback, flag or no flag."""
    monkeypatch.delenv("WEB_TRUST_FORWARDED_FOR", raising=False)
    uri = await _login_redirect_uri(auth0_service, "tenant.example.com", "https")
    assert uri == "https://tenant.example.com/auth/callback"


# --- review follow-up: the flag nobody sets ----------------------------------


def _real_request(headers: dict[str, str]) -> Request:
    """A real Starlette Request, built from a scope — not a stand-in object."""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "scheme": "http",
            "query_string": b"",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": HEROKU_ROUTER_PEER,
            "server": ("testserver", 80),
        }
    )


# --- review follow-up: first-vs-last X-Forwarded-Proto -----------------------


def test_forwarded_proto_is_trusted_only_when_its_values_agree(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agreement is the only usable signal in a multi-hop chain.

    My first attempt claimed the leftmost entry was safe either way. It is not:
    a client's `https` plus an appending proxy's `http` puts the forgery first.
    My second attempt refused every multi-valued header, which would have
    broken Cloudflare Full mode (`https, https`) — the configuration the docs
    recommend. Values that agree are trustworthy; values that disagree are not.
    """
    monkeypatch.setenv("WEB_TRUST_FORWARDED_FOR", "true")

    assert request_scheme(_real_request({"x-forwarded-proto": "https"})) == "https"
    assert request_scheme(_real_request({"x-forwarded-proto": "https, https"})) == "https"
    # Comma form and duplicate header lines are the same input in two spellings.
    assert request_scheme(_real_request({"x-forwarded-proto": "https, http"})) == "http"
    assert request_scheme(_duplicated_proto_request("https", "http")) == "http"
    assert request_scheme(_duplicated_proto_request("https", "https")) == "https"


def _duplicated_proto_request(*values: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "scheme": "http",
            "query_string": b"",
            "headers": [(b"x-forwarded-proto", value.encode()) for value in values],
            "client": HEROKU_ROUTER_PEER,
            "server": ("testserver", 80),
        }
    )
