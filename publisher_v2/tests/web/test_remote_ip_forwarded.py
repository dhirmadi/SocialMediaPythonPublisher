"""SEC-2 (#77): X-Forwarded-For parsing and the unkeyed global login budget.

Heroku's router APPENDS the real client IP on the right of X-Forwarded-For;
the leftmost entries are attacker-chosen. remote_ip() must therefore take the
rightmost entry when WEB_TRUST_FORWARDED_FOR is enabled, and the login
endpoint needs a global (unkeyed) failure budget that spoofed per-IP keys
cannot reset.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
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


class TestGlobalLoginBudget:
    @pytest.fixture
    def client(self, monkeypatch: pytest.MonkeyPatch):
        from publisher_v2.web import app as app_module

        # Importing publisher_v2.web.service runs load_dotenv() once per
        # process, which can re-introduce workspace env; clear after import.
        monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
        monkeypatch.setenv("WEB_DEBUG", "1")
        monkeypatch.setenv("web_admin_pw", "correct-password")
        monkeypatch.setenv("WEB_TRUST_FORWARDED_FOR", "true")
        # Disable the exponential failure backoff so the test runs fast.
        monkeypatch.setenv("WEB_LOGIN_BACKOFF_CAP_SECONDS", "0")
        monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)
        monkeypatch.setenv("CONFIG_SOURCE", "env")

        # Reset process-local limiter state so other tests don't bleed in.
        app_module._LOGIN_LIMITER.reset()
        app_module._GLOBAL_LOGIN_LIMITER.reset()
        with TestClient(app_module.app) as c:
            yield c
        app_module._LOGIN_LIMITER.reset()
        app_module._GLOBAL_LOGIN_LIMITER.reset()

    def test_forty_failures_with_distinct_forwarded_ips_hit_global_429(self, client: TestClient) -> None:
        """Spoofing a fresh X-Forwarded-For per request must not reset the budget."""
        saw_429 = False
        for i in range(40):
            res = client.post(
                "/api/admin/login",
                json={"password": "wrong"},
                headers={"X-Forwarded-For": f"198.51.100.{i}, 10.0.0.5"},
            )
            assert res.status_code in (401, 429)
            if res.status_code == 429:
                saw_429 = True
                assert "Retry-After" in res.headers
        assert saw_429, "global login budget never engaged despite 40 failures"


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
