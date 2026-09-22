"""PUB-048 AC3/AC4 (#187): CSRF is bypassed only by an Authorization header that verifies.

`CSRFMiddleware.dispatch` currently bypasses CSRF on the mere *presence* of an
`Authorization` header. `POST /api/auth/logout` has no auth dependency of its
own, so a bogus Bearer plus a stolen-but-valid cookie revokes the victim's
session from a cross-site page, with no `X-Requested-With`.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

VALID_TOKEN = "csrf-test-token"


@pytest.fixture
def cookie_client(monkeypatch: pytest.MonkeyPatch, env_first_config: None) -> Generator[TestClient, None, None]:
    """Real app, real `_verify_bearer`/`_verify_basic`, browser-shaped cookie session."""
    from publisher_v2.web.app import app

    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
    monkeypatch.setenv("WEB_AUTH_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    monkeypatch.setenv("AUTH0_CLIENT_ID", "cid")
    monkeypatch.delenv("WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)

    from publisher_v2.web.auth import ADMIN_COOKIE_NAME, mint_admin_cookie_value

    client = TestClient(app)
    client.cookies.set(ADMIN_COOKIE_NAME, mint_admin_cookie_value(host="testserver"))
    yield client


def _still_admin(client: TestClient) -> bool:
    """Whether the session the cookie represents is still live server-side."""
    return bool(client.get("/api/admin/status").json()["admin"])


class TestCsrfBypassRequiresVerifiedHeader:
    """AC3: an unverifiable Authorization header must not buy a CSRF bypass."""

    def test_invalid_bearer_with_cookie_and_no_x_requested_with_is_blocked_and_session_not_revoked(
        self, cookie_client: TestClient
    ) -> None:
        assert _still_admin(cookie_client) is True, "fixture did not establish an admin session"

        res = cookie_client.post("/api/auth/logout", headers={"Authorization": "Bearer nope"})

        assert res.status_code == 403, "a bogus Bearer bypassed CSRF on a cross-site logout"
        assert res.json()["detail"] == "CSRF check failed"
        assert _still_admin(cookie_client) is True, "the victim's session was revoked by a blocked request"


class TestCsrfBypassStillWorksForMachineClients:
    """AC4: a header that verifies keeps its bypass — the regression guard for AC3's fix."""

    def test_valid_bearer_bypasses_csrf_without_x_requested_with(self, cookie_client: TestClient) -> None:
        res = cookie_client.post("/api/auth/logout", headers={"Authorization": f"Bearer {VALID_TOKEN}"})

        assert res.status_code == 200, "a valid Bearer was blocked by CSRF"
        assert res.json()["admin"] is False
