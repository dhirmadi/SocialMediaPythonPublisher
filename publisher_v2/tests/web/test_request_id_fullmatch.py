"""#144 item 7: the request-id filter used re.match with a trailing $.

``$`` also matches just before a final newline, so "abc\n" passed the pattern
and a newline reached the correlation id — and every log line built from it.
Exercised through the real app's middleware, not the compiled pattern.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from .conftest import RealAppEnv


@pytest.fixture
def real_app(real_app_env: Callable[..., RealAppEnv]) -> RealAppEnv:
    """The real app on Dropbox storage, one image in the folder (``tests/web/conftest.py``)."""
    return real_app_env()


async def _correlation_id(header: str) -> str:
    """The id the real app echoes back on a request carrying this X-Request-ID."""
    from publisher_v2.web.app import app
    from publisher_v2.web.auth import ADMIN_COOKIE_NAME, mint_admin_cookie_value

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        cookies={ADMIN_COOKIE_NAME: mint_admin_cookie_value(host="testserver")},
    ) as client:
        response = await client.get("/api/images/img.jpg", headers={"X-Request-ID": header})
    assert response.status_code == 200, (response.status_code, response.text[:200])
    return response.headers["X-Correlation-ID"]


async def test_trailing_newline_is_rejected(real_app: RealAppEnv) -> None:
    returned = await _correlation_id("abc123\n")

    assert returned != "abc123\n"
    assert "\n" not in returned


async def test_clean_request_id_is_still_honoured(real_app: RealAppEnv) -> None:
    assert await _correlation_id("abc123") == "abc123"
