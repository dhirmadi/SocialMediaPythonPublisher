from __future__ import annotations

import json
import logging
import os
from typing import Any

import pytest
from conftest import BaseDummyStorage
from fastapi.testclient import TestClient

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
)
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.web.app import app


class _DummyStorage(BaseDummyStorage):
    pass


class _DummyAnalyzer:
    async def analyze(self, url_or_bytes: str | bytes) -> tuple[Any, None]:
        from publisher_v2.core.models import ImageAnalysis

        return ImageAnalysis(
            description="Test image",
            mood="neutral",
            tags=["test"],
            nsfw=False,
            safety_labels=[],
        ), None


class _DummyGenerator:
    async def generate(self, analysis: Any, spec: Any) -> tuple[str, None]:
        return "hello world", None


class _DummyAI(AIService):
    def __init__(self) -> None:
        self.analyzer = _DummyAnalyzer()  # type: ignore[assignment]
        self.generator = _DummyGenerator()  # type: ignore[assignment]

        # Provide a no-op rate limiter compatible with AIService usage.
        class _NoopLimiter:
            async def __aenter__(self) -> None:  # type: ignore[override]
                return None

            async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[override]
                return False

        self._rate_limiter = _NoopLimiter()  # type: ignore[assignment]


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
    cfg = ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        ),
        storage_paths=StoragePathConfig(image_folder="/Photos"),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(telegram_enabled=False, instagram_enabled=False, email_enabled=False),
        telegram=None,
        instagram=None,
        email=None,
        content=ContentConfig(hashtag_string="#tags", archive=False, debug=False),
    )

    storage = _DummyStorage()
    ai = _DummyAI()
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
