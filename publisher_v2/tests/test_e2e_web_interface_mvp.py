from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from publisher_v2.web.app import app


@pytest.mark.skipif(
    not os.path.exists(os.environ.get("CONFIG_PATH", "configfiles/fetlife.ini")),
    reason="Requires CONFIG_PATH pointing to a real config and Dropbox/OpenAI credentials",
)
def test_web_interface_end_to_end() -> None:
    """
    Lightweight e2e-style test that exercises the web app stack using TestClient.

    In CI this can be enabled when CONFIG_PATH and credentials are available.
    """
    client = TestClient(app)

    # Health check
    res = client.get("/health")
    assert res.status_code == 200

    # Load page HTML
    res = client.get("/")
    assert res.status_code == 200
    assert "Publisher V2 Web" in res.text


