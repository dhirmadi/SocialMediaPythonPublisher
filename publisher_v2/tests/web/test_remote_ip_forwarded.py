"""SEC-2 (#77): X-Forwarded-For parsing and the unkeyed global login budget.

Heroku's router APPENDS the real client IP on the right of X-Forwarded-For;
the leftmost entries are attacker-chosen. remote_ip() must therefore take the
rightmost entry when WEB_TRUST_FORWARDED_FOR is enabled, and the login
endpoint needs a global (unkeyed) failure budget that spoofed per-IP keys
cannot reset.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from publisher_v2.web.rate_limit import remote_ip


def _request_with_xff(xff: str | None, client_host: str = "10.1.2.3") -> Request:
    headers = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "query_string": b"",
        "client": (client_host, 12345),
    }
    return Request(scope)


def test_remote_ip_takes_rightmost_forwarded_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_TRUST_FORWARDED_FOR", "true")
    request = _request_with_xff("1.1.1.1, 10.0.0.5, 203.0.113.9")
    assert remote_ip(request) == "203.0.113.9"


def test_remote_ip_trust_disabled_uses_client_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEB_TRUST_FORWARDED_FOR", raising=False)
    request = _request_with_xff("1.1.1.1, 10.0.0.5, 203.0.113.9", client_host="10.1.2.3")
    assert remote_ip(request) == "10.1.2.3"


def test_auth0_callback_url_https_behind_heroku_router() -> None:
    """Regression (commit 68d3a7f): non-local hosts must yield https callback
    even when the proxy scheme header is not applied to request.url."""
    from publisher_v2.web.routers.auth import get_auth0_callback_url

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",  # uvicorn did not rewrite the scheme
        "path": "/auth/login",
        "raw_path": b"/auth/login",
        "query_string": b"",
        "headers": [
            (b"host", b"tenant.example.com"),
            (b"x-forwarded-proto", b"https"),
        ],
        "client": ("10.0.0.1", 50000),
        "server": ("tenant.example.com", 80),
    }
    request = Request(scope)
    assert get_auth0_callback_url(request) == "https://tenant.example.com/auth/callback"
