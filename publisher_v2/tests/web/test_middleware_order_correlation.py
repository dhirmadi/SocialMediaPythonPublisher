"""SEC-12 (#87): correlation-id hygiene and middleware ordering."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, patch

import pytest
from starlette.requests import Request

from publisher_v2.core.exceptions import TenantNotFoundError


def _request_with_request_id(value: str | None) -> Request:
    headers = []
    if value is not None:
        headers.append((b"x-request-id", value.encode("latin-1")))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "query_string": b""})


_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class TestCorrelationId:
    def test_valid_header_is_echoed(self) -> None:
        from publisher_v2.web.app import _get_correlation_id

        assert _get_correlation_id(_request_with_request_id("req-1.2_A")) == "req-1.2_A"

    def test_overlong_header_replaced_with_uuid(self) -> None:
        from publisher_v2.web.app import _get_correlation_id

        result = _get_correlation_id(_request_with_request_id("a" * 129))
        assert _UUID_RE.match(result)

    def test_invalid_characters_replaced_with_uuid(self) -> None:
        from publisher_v2.web.app import _get_correlation_id

        result = _get_correlation_id(_request_with_request_id('abc"<script>'))
        assert _UUID_RE.match(result)

    def test_missing_header_generates_uuid(self) -> None:
        from publisher_v2.web.app import _get_correlation_id

        assert _UUID_RE.match(_get_correlation_id(_request_with_request_id(None)))


class TestMiddlewareOrder:
    def test_unknown_tenant_404_carries_security_headers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The tenant middleware's 404 must pass through SecurityHeaders — it
        used to be registered outermost, so those JSON errors had no CSP."""
        from fastapi.testclient import TestClient

        monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
        monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orch.example.test")
        monkeypatch.delenv("CONFIG_SOURCE", raising=False)

        source = AsyncMock()
        source.get_config.side_effect = TenantNotFoundError("nope")
        with patch("publisher_v2.web.middleware.get_config_source", return_value=source):
            from publisher_v2.web.app import app

            client = TestClient(app)
            res = client.get("/api/images")

        assert res.status_code == 404
        assert "content-security-policy" in res.headers
        assert res.headers.get("x-content-type-options") == "nosniff"
