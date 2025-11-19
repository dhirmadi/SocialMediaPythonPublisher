from __future__ import annotations

import base64
import os

import pytest
from fastapi.testclient import TestClient

from publisher_v2.web.app import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
  # Ensure CONFIG_PATH exists; if not, skip tests.
  cfg = os.environ.get("CONFIG_PATH", "configfiles/fetlife.ini")
  if not os.path.exists(cfg):
      pytest.skip("CONFIG_PATH does not point to a real config; skip web auth integration tests")
  monkeypatch.setenv("CONFIG_PATH", cfg)
  monkeypatch.setenv("WEB_AUTH_TOKEN", "secret-token")
  return TestClient(app)


def test_analyze_requires_auth(client: TestClient) -> None:
  res = client.post("/api/images/test.jpg/analyze")
  assert res.status_code in (401, 404)


def test_publish_requires_auth(client: TestClient) -> None:
  res = client.post("/api/images/test.jpg/publish")
  assert res.status_code in (401, 404)


