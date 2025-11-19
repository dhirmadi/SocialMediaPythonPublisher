from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from publisher_v2.web.app import app


@pytest.fixture(autouse=True)
def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure CONFIG_PATH is set to something so WebImageService can be constructed.
    # In integration tests we rely on a real-ish config file; if not present,
    # these tests can be skipped by the user.
    monkeypatch.setenv("CONFIG_PATH", os.environ.get("CONFIG_PATH", "configfiles/fetlife.ini"))


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_endpoint(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}



