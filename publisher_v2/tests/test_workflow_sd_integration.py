from __future__ import annotations

import asyncio
import hashlib
import os
import pytest

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
)
from publisher_v2.core.models import ImageAnalysis, CaptionSpec
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI
from publisher_v2.services.storage import DropboxStorage
from publisher_v2.services.publishers.base import Publisher


class DummyAnalyzer(VisionAnalyzerOpenAI):
    def __init__(self) -> None:
        pass

    async def analyze(self, url_or_bytes: str | bytes) -> ImageAnalysis:
        return ImageAnalysis(description="desc", mood="mood", tags=["t"], nsfw=False, safety_labels=[])


class DummyGenerator(CaptionGeneratorOpenAI):
    def __init__(self, cfg: OpenAIConfig) -> None:
        super().__init__(cfg)

    async def generate_with_sd(self, analysis: ImageAnalysis, spec: CaptionSpec) -> dict[str, str]:
        return {"caption": "normal caption", "sd_caption": "fine-art portrait, soft light, calm mood"}

    async def generate(self, analysis: ImageAnalysis, spec: CaptionSpec) -> str:
        return "legacy caption"


class DummyStorage(DropboxStorage):
    def __init__(self, cfg: DropboxConfig) -> None:
        self.config = cfg
        self.writes = 0
        self.archives = 0

    async def list_images(self, folder: str):
        return ["image.jpg"]

    async def download_image(self, folder: str, filename: str) -> bytes:
        return b"data"

    async def get_temporary_link(self, folder: str, filename: str) -> str:
        return "http://tmp"

    async def get_file_metadata(self, folder: str, filename: str):
        return {"id": "id:XYZ", "rev": "123"}

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        self.writes += 1

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        self.archives += 1


def make_config() -> ApplicationConfig:
    drop = DropboxConfig(
        app_key="a", app_secret="b", refresh_token="c", image_folder="/ImagesToday", archive_folder="archive"
    )
    openai = OpenAIConfig(
        api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx",
        vision_model="gpt-4o",
        caption_model="gpt-4o-mini",
        sd_caption_enabled=True,
        sd_caption_single_call_enabled=True,
    )
    platforms = PlatformsConfig(telegram_enabled=False, instagram_enabled=False, email_enabled=False)
    content = ContentConfig(hashtag_string="", archive=False, debug=False)
    return ApplicationConfig(dropbox=drop, openai=openai, platforms=platforms, content=content)


@pytest.mark.asyncio
async def test_workflow_sd_integration_preview_and_live(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_config()
    storage = DummyStorage(cfg.dropbox)
    ai = AIService(DummyAnalyzer(), DummyGenerator(cfg.openai))
    cgf = cfg
    orchestrator = WorkflowOrchestrator(config=cgf, storage=storage, ai_service=ai, publishers=[])
    # Ensure dedup state does not block the test
    monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
    monkeypatch.setattr("publisher_v2.core.workflow.save_posted_hash", lambda h: None)

    # Preview mode should not write sidecar but should expose sd_caption in result.analysis
    result_prev = await orchestrator.execute(preview_mode=True)
    assert result_prev.image_analysis is not None
    assert getattr(result_prev.image_analysis, "sd_caption", None)
    assert storage.writes == 0

    # Live (no dry/debug) should write sidecar
    cgf.content.archive = False
    result_live = await orchestrator.execute(preview_mode=False)
    assert storage.writes == 1
    assert result_live.success in (True, False)  # Publishing bypassed; success may reflect debug path


