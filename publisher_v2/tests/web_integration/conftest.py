"""Shared fixtures for web_integration tests."""

from __future__ import annotations

from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def _reset_web_rate_limiters() -> Generator[None, None, None]:
    """Per-test reset of the in-memory limiters in publisher_v2.web.app.

    Without this, the brute-force-login and analyze/publish limiters accumulate
    counts across tests since they're module-level singletons. That makes the
    8th login attempt in the test suite 429 even though each test only invokes
    login once.
    """
    from publisher_v2.web import app as _app

    for limiter_name in (
        "_LOGIN_LIMITER",
        "_ANALYZE_LIMITER_MIN",
        "_ANALYZE_LIMITER_HOUR",
        "_PUBLISH_LIMITER_MIN",
    ):
        limiter = getattr(_app, limiter_name, None)
        if limiter is not None:
            limiter.reset()
    yield
