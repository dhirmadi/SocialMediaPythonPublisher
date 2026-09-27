from __future__ import annotations

import json
import logging
import os
from typing import Any

import pytest
from caption_pipeline_fakes import BaseDummyStorage, make_app_config, stub_ai_service
from fastapi.testclient import TestClient

from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.web.app import app


class _DummyStorage(BaseDummyStorage):
    pass


class _DummyPublisher(Publisher):
    @property
    def platform_name(self) -> str:
        return "dummy"

    def is_enabled(self) -> bool:
        return False

    async def publish(self, image_path: str, caption: str) -> Any:  # type: ignore[override]
        return None


@pytest.mark.asyncio
async def test_cli_workflow_emits_timing_log(caplog: pytest.LogCaptureFixture) -> None:
    cfg = make_app_config(content={"hashtag_string": "#tags"})

    storage = _DummyStorage()
    ai = stub_ai_service()
    publishers: list[Publisher] = [_DummyPublisher()]
    orchestrator = WorkflowOrchestrator(cfg, storage, ai, publishers)

    caplog.set_level(logging.INFO, logger="publisher_v2.workflow")

    await orchestrator.execute()

    records = [r for r in caplog.records if "workflow_timing" in r.getMessage()]
    assert records, "Expected workflow_timing log for CLI run"
    entry: dict[str, Any] = json.loads(records[0].getMessage())
    assert entry.get("correlation_id")
    assert isinstance(entry.get("dropbox_list_images_ms"), int)
    assert isinstance(entry.get("image_selection_ms"), int)
    assert isinstance(entry.get("vision_analysis_ms"), int)
    assert isinstance(entry.get("caption_generation_ms"), int)


def test_web_random_image_emits_telemetry(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    # #97 stage 4: INI removed — this e2e needs a real-ish env-first config.
    # The autouse env-isolation fixture clears the JSON config vars, so re-load
    # them from the workspace .env when present; skip otherwise (e.g. CI).
    if not os.path.exists(".env"):
        pytest.skip("Requires a workspace .env with STORAGE_PATHS/PUBLISHERS/OPENAI_SETTINGS")
    from dotenv import dotenv_values

    values = dotenv_values(".env")
    if not (values.get("STORAGE_PATHS") and values.get("OPENAI_SETTINGS")):
        pytest.skip("Workspace .env lacks env-first config vars")
    needed = (
        "STORAGE_PATHS",
        "OPENAI_SETTINGS",
        "DROPBOX_APP_KEY",
        "DROPBOX_APP_SECRET",
        "DROPBOX_REFRESH_TOKEN",
        "OPENAI_API_KEY",
    )
    for key in needed:
        if values.get(key):
            monkeypatch.setenv(key, values[key])
    monkeypatch.setenv("PUBLISHERS", "[]")
    monkeypatch.delenv("CONFIG_PATH", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)
    # #135: never reuse a WebImageService/config source cached by an earlier test.
    from publisher_v2.config.source import get_config_source
    from publisher_v2.web.dependencies import get_service

    get_config_source.cache_clear()
    get_service.cache_clear()
    request.addfinalizer(get_service.cache_clear)
    request.addfinalizer(get_config_source.cache_clear)
    client = TestClient(app)

    caplog.set_level(logging.INFO, logger="publisher_v2.web")

    # We only care that the endpoint runs enough to emit logs; underlying Dropbox/OpenAI
    # may be mocked/controlled by other tests or environment.
    res = client.get("/api/images/random")
    # 404 is acceptable if no images are configured; 403/503 are acceptable when
    # admin-gated or misconfigured. In all cases we still expect telemetry logs.
    assert res.status_code in (200, 403, 404, 503)

    records = [
        r for r in caplog.records if "web_random_image" in r.getMessage() or "view_permission_denied" in r.getMessage()
    ]
    assert records, "Expected web_random_image* or view_permission_denied* log entry"
    entry = json.loads(records[0].getMessage())
    assert entry.get("correlation_id")
    # permission denied logs might not have web_random_image_ms, but success/error paths do.
    # checking correlation_id is sufficient proof of telemetry.
    if "web_random_image_ms" in entry:
        assert isinstance(entry.get("web_random_image_ms"), int)
