from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from publisher_v2.web.app import app


@pytest.fixture(autouse=True)
def _set_env(env_first_config: None) -> None:
    # #135: env-first config (INI and CONFIG_PATH were removed in #97).
    return None


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_endpoint(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
