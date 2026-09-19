from __future__ import annotations

from fastapi.testclient import TestClient

from publisher_v2.web.app import app


def test_web_interface_end_to_end(env_first_config: None) -> None:
    """
    Lightweight e2e-style test that exercises the web app stack using TestClient.

    #135: runs everywhere on the env-first fixture (the INI-file gate it had
    meant CI always skipped it).
    """
    client = TestClient(app)

    # Health check
    res = client.get("/health")
    assert res.status_code == 200

    # Load page HTML
    res = client.get("/")
    assert res.status_code == 200
    assert "Publisher V2 Web" in res.text
