from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Dict, List

import pytest

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
)
from publisher_v2.core.models import CaptionSpec, PublishResult
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.services.storage import DropboxStorage


class DummyStorage(DropboxStorage):
    def __init__(self):
        # Bypass parent init
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


class DummyAnalyzer:
    async def analyze(self, url_or_bytes: str | bytes):
        from publisher_v2.core.models import ImageAnalysis
        return ImageAnalysis(
            description="Test image",
            mood="neutral",
            tags=["test"],
            nsfw=False,
            safety_labels=[],
        )


class DummyGenerator:
    async def generate(self, analysis, spec: CaptionSpec) -> str:
        return "hello world #tags"


class DummyAI(AIService):
    def __init__(self):
        self._caption = "hello world #tags"
        self.analyzer = DummyAnalyzer()
        self.generator = DummyGenerator()
        # Provide a no-op rate limiter compatible with AIService usage.
        class _NoopLimiter:
            async def __aenter__(self) -> None:  # type: ignore[override]
                return None

            async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[override]
                return False

        self._rate_limiter = _NoopLimiter()

    async def create_caption(self, url_or_bytes: str | bytes, spec: CaptionSpec) -> str:
        return self._caption


class DummyPublisher(Publisher):
    @property
    def platform_name(self) -> str:
        return "dummy"

    def is_enabled(self) -> bool:
        return True

    async def publish(self, image_path: str, caption: str) -> PublishResult:
        # Should not be called in debug mode
        return PublishResult(success=False, platform=self.platform_name, error="should not be called")


@pytest.mark.asyncio
async def test_orchestrator_debug_mode_skips_publish_and_no_archive(tmp_path):
    cfg = ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        ),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(telegram_enabled=False, instagram_enabled=False, email_enabled=False),
        telegram=None,
        instagram=None,
        email=None,
        content=ContentConfig(hashtag_string="#tags", archive=True, debug=True),
    )
    storage = DummyStorage()
    ai = DummyAI()
    publishers = [DummyPublisher()]
    orchestrator = WorkflowOrchestrator(cfg, storage, ai, publishers)
    result = await orchestrator.execute()

    assert result.success is True
    assert result.archived is False
    assert result.image_name == "test.jpg"
    assert result.caption.startswith("hello world")
    assert "dummy" in result.publish_results
    assert result.publish_results["dummy"].success is True


@pytest.mark.asyncio
async def test_orchestrator_emits_timing_log(tmp_path, caplog: pytest.LogCaptureFixture) -> None:
    cfg = ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        ),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(telegram_enabled=False, instagram_enabled=False, email_enabled=False),
        telegram=None,
        instagram=None,
        email=None,
        content=ContentConfig(hashtag_string="#tags", archive=True, debug=True),
    )
    storage = DummyStorage()
    ai = DummyAI()
    publishers = [DummyPublisher()]
    orchestrator = WorkflowOrchestrator(cfg, storage, ai, publishers)

    caplog.set_level(logging.INFO, logger="publisher_v2.workflow")

    await orchestrator.execute()

    records = [r for r in caplog.records if "workflow_timing" in r.getMessage()]
    assert records, "Expected a workflow_timing log entry"

    entry = json.loads(records[0].getMessage())
    assert entry.get("correlation_id")
    assert isinstance(entry.get("dropbox_list_images_ms"), int)
    assert isinstance(entry.get("image_selection_ms"), int)
    assert isinstance(entry.get("caption_generation_ms"), int)


