from __future__ import annotations

import pytest

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
)
from publisher_v2.core.models import ImageAnalysis, CaptionSpec, PublishResult
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
        self.sidecars = 0
        self.archived = 0

    async def list_images(self, folder: str):
        return ["image.jpg"]

    async def download_image(self, folder: str, filename: str) -> bytes:
        return b"data"

    async def get_temporary_link(self, folder: str, filename: str) -> str:
        return "http://tmp"

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        self.sidecars += 1

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        self.archived += 1


class DummyPublisher(Publisher):
    @property
    def platform_name(self) -> str:
        return "dummy"

    def is_enabled(self) -> bool:
        return True

    async def publish(self, image_path: str, caption: str, context: dict | None = None) -> PublishResult:
        return PublishResult(success=True, platform=self.platform_name)


def make_config(archive: bool) -> ApplicationConfig:
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
    content = ContentConfig(hashtag_string="", archive=archive, debug=False)
    return ApplicationConfig(dropbox=drop, openai=openai, platforms=platforms, content=content)


@pytest.mark.asyncio
async def test_e2e_preview_then_live_sd_caption() -> None:
    # Preview phase
    cfg_prev = make_config(archive=True)
    storage_prev = DummyStorage(cfg_prev.dropbox)
    ai_prev = AIService(DummyAnalyzer(), DummyGenerator(cfg_prev.openai))
    orch_prev = WorkflowOrchestrator(config=cfg_prev, storage=storage_prev, ai_service=ai_prev, publishers=[DummyPublisher()])
    result_prev = await orch_prev.execute(preview_mode=True)
    assert result_prev.image_analysis is not None
    assert getattr(result_prev.image_analysis, "sd_caption", None)
    assert storage_prev.sidecars == 0  # no side effects in preview

    # Live phase
    cfg_live = make_config(archive=True)
    storage_live = DummyStorage(cfg_live.dropbox)
    ai_live = AIService(DummyAnalyzer(), DummyGenerator(cfg_live.openai))
    orch_live = WorkflowOrchestrator(config=cfg_live, storage=storage_live, ai_service=ai_live, publishers=[DummyPublisher()])
    result_live = await orch_live.execute(preview_mode=False)
    assert storage_live.sidecars == 1
    # With a successful publisher and archive enabled, archive is called
    assert storage_live.archived == 1


