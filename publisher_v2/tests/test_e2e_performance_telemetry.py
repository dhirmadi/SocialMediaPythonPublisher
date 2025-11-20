from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from publisher_v2.web.app import app
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.config.schema import ApplicationConfig, ContentConfig, DropboxConfig, OpenAIConfig, PlatformsConfig
from publisher_v2.services.ai import AIService
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.services.storage import DropboxStorage


class _DummyStorage(DropboxStorage):
    def __init__(self) -> None:
        self.config = DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        )

    async def list_images(self, folder: str) -> List[str]:
        return ["test.jpg"]

    async def download_image(self, folder: str, filename: str) -> bytes:
        return b"\x89PNG\r\n\x1a\n"

    async def get_temporary_link(self, folder: str, filename: str) -> str:
        return "https://example.com/tmp/test.jpg"

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        return None


class _DummyAnalyzer:
    async def analyze(self, url_or_bytes: str | bytes) -> Any:
        from publisher_v2.core.models import ImageAnalysis

        return ImageAnalysis(
            description="Test image",
            mood="neutral",
            tags=["test"],
            nsfw=False,
            safety_labels=[],
        )


class _DummyGenerator:
    async def generate(self, analysis: Any, spec: Any) -> str:
        return "hello world"


class _DummyAI(AIService):
    def __init__(self) -> None:
        self.analyzer = _DummyAnalyzer()
        self.generator = _DummyGenerator()
        # Provide a no-op rate limiter compatible with AIService usage.
        class _NoopLimiter:
            async def __aenter__(self) -> None:  # type: ignore[override]
                return None

            async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[override]
                return False

        self._rate_limiter = _NoopLimiter()


class _DummyPublisher(Publisher):
    @property
    def platform_name(self) -> str:
        return "dummy"

    def is_enabled(self) -> bool:
        return False

    async def publish(self, image_path: str, caption: str) -> Any:
        return None


@pytest.mark.asyncio
async def test_cli_workflow_emits_timing_log(caplog: pytest.LogCaptureFixture) -> None:
    cfg = ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        ),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(telegram_enabled=False, instagram_enabled=False, email_enabled=False),
        telegram=None,
        instagram=None,
        email=None,
        content=ContentConfig(hashtag_string="#tags", archive=False, debug=False),
    )

    storage = _DummyStorage()
    ai = _DummyAI()
    publishers: List[Publisher] = [_DummyPublisher()]
    orchestrator = WorkflowOrchestrator(cfg, storage, ai, publishers)

    caplog.set_level(logging.INFO, logger="publisher_v2.workflow")

    await orchestrator.execute()

    records = [r for r in caplog.records if "workflow_timing" in r.getMessage()]
    assert records, "Expected workflow_timing log for CLI run"
    entry: Dict[str, Any] = json.loads(records[0].getMessage())
    assert entry.get("correlation_id")
    assert isinstance(entry.get("dropbox_list_images_ms"), int)
    assert isinstance(entry.get("image_selection_ms"), int)
    assert isinstance(entry.get("vision_analysis_ms"), int)
    assert isinstance(entry.get("caption_generation_ms"), int)


def test_web_random_image_emits_telemetry(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    # Skip if no config is available; this mirrors other web e2e tests which
    # require a real-ish CONFIG_PATH to run.
    if not os.path.exists("configfiles/fetlife.ini"):
        pytest.skip("Requires CONFIG_PATH pointing to a real config and Dropbox/OpenAI credentials")

    monkeypatch.setenv("CONFIG_PATH", "configfiles/fetlife.ini")
    client = TestClient(app)

    caplog.set_level(logging.INFO, logger="publisher_v2.web")

    # We only care that the endpoint runs enough to emit logs; underlying Dropbox/OpenAI
    # may be mocked/controlled by other tests or environment.
    res = client.get("/api/images/random")
    # 404 is acceptable if no images are configured; telemetry should still log.
    assert res.status_code in (200, 404)

    records = [r for r in caplog.records if "web_random_image" in r.getMessage() or "web_random_image_error" in r.getMessage()]
    assert records, "Expected web_random_image* log entry"
    entry = json.loads(records[0].getMessage())
    assert entry.get("correlation_id")
    assert isinstance(entry.get("web_random_image_ms"), int)


