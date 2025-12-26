from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from publisher_v2.web.app import app
from publisher_v2.config.source import clear_config_source_cache


def test_health_live_always_ok() -> None:
    client = TestClient(app)
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_ready_standalone_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure env-first mode
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_SERVICE_TOKEN", raising=False)
    clear_config_source_cache()
    client = TestClient(app)
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_ready_orchestrator_down(monkeypatch: pytest.MonkeyPatch) -> None:
    # Configure orchestrator mode but force connectivity check to fail via bad URL.
    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orch.test")
    monkeypatch.setenv("ORCHESTRATOR_SERVICE_TOKEN", "svc-token")
    monkeypatch.setenv("DROPBOX_APP_KEY", "app_key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "app_secret")
    clear_config_source_cache()

    # Monkeypatch the source connectivity check to raise
    from publisher_v2.config import source as source_mod
    from publisher_v2.core.exceptions import OrchestratorUnavailableError

    src = source_mod.get_config_source()
    assert src.is_orchestrated() is True

    async def boom() -> None:
        raise OrchestratorUnavailableError("down")

    setattr(src, "check_connectivity", boom)

    client = TestClient(app)
    r = client.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "not_ready"


