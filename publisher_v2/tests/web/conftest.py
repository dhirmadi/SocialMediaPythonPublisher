"""Shared fixtures for web layer tests."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def managed_admin_client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """TestClient configured for managed storage with admin."""
    monkeypatch.setenv("WEB_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("web_admin_pw", "secret")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
    monkeypatch.setenv("WEB_DEBUG", "true")
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)
    monkeypatch.setenv("CONFIG_SOURCE", "env")

    from publisher_v2.config.source import get_config_source

    get_config_source.cache_clear()

    from publisher_v2.web.app import app

    client = TestClient(app)
    yield client

    get_config_source.cache_clear()
