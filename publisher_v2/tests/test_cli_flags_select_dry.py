from __future__ import annotations

import pytest

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
)
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.services.storage import DropboxStorage


class DummyStorageSelect(DropboxStorage):
    def __init__(self):
        self.config = DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        )

    async def list_images(self, folder: str):
        return ["x.jpg", "y.jpg"]

    async def download_image(self, folder: str, filename: str) -> bytes:
        return b"content-" + filename.encode()

    async def get_temporary_link(self, folder: str, filename: str) -> str:
        return f"https://example.com/tmp/{filename}"

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        return None


class DummyAnalyzer3:
    async def analyze(self, url_or_bytes: str | bytes):
        from publisher_v2.core.models import ImageAnalysis
        return ImageAnalysis(
            description="Test image",
            mood="neutral",
            tags=["test"],
            nsfw=False,
            safety_labels=[],
        )


class DummyGenerator3:
    async def generate(self, analysis, spec) -> str:
        return "caption #h"


class DummyAI3(AIService):
    def __init__(self):
        self._caption = "caption #h"
        self.analyzer = DummyAnalyzer3()
        self.generator = DummyGenerator3()

    async def create_caption(self, url_or_bytes: str | bytes, spec):
        return self._caption


class DummyPub(Publisher):
    @property
    def platform_name(self) -> str:
        return "dummy"

    def is_enabled(self) -> bool:
        return True

    async def publish(self, image_path: str, caption: str):
        return NotImplemented  # should not be called in dry publish


@pytest.mark.asyncio
async def test_select_and_dry_publish_skip_real_publish(monkeypatch):
    cfg = ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        ),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(telegram_enabled=False, instagram_enabled=False, email_enabled=False),
        telegram=None,
        instagram=None,
        email=None,
        content=ContentConfig(hashtag_string="#h", archive=True, debug=False),
    )
    storage = DummyStorageSelect()
    ai = DummyAI3()
    orch = WorkflowOrchestrator(cfg, storage, ai, [DummyPub()])
    result = await orch.execute(select_filename="y.jpg", dry_publish=True)
    assert result.success is True
    assert result.image_name == "y.jpg"
    assert result.archived is False
    assert "dummy" in result.publish_results and result.publish_results["dummy"].success is True


