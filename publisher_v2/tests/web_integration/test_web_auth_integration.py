from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from publisher_v2.web.app import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, env_first_config: None) -> TestClient:
    monkeypatch.setenv("WEB_AUTH_TOKEN", "secret-token")
    return TestClient(app)


def test_analyze_requires_auth(client: TestClient) -> None:
    res = client.post("/api/images/test.jpg/analyze")
    assert res.status_code in (401, 404)


def test_publish_requires_auth(client: TestClient) -> None:
    res = client.post("/api/images/test.jpg/publish")
    assert res.status_code in (401, 404)
