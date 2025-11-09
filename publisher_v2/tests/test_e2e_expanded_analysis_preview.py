from __future__ import annotations

import pytest

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
)
from publisher_v2.core.models import ImageAnalysis
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI
from publisher_v2.services.storage import DropboxStorage
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.core.models import CaptionSpec, PublishResult


class DummyAnalyzer(VisionAnalyzerOpenAI):
    def __init__(self) -> None:
        pass

    async def analyze(self, url_or_bytes: str | bytes) -> ImageAnalysis:
        return ImageAnalysis(
            description="Fine-art portrait, soft light.",
            mood="calm",
            tags=["portrait", "softlight"],
            nsfw=False,
            safety_labels=[],
            subject="single subject, torso",
            style="fine-art",
            lighting="soft directional",
            camera="50mm",
            clothing_or_accessories="rope harness",
            aesthetic_terms=["minimalist", "graphic"],
            pose="upright",
            composition="center-weighted",
            background="plain backdrop",
            color_palette="black and white",
        )


class DummyGenerator(CaptionGeneratorOpenAI):
    def __init__(self, cfg: OpenAIConfig) -> None:
        super().__init__(cfg)

    async def generate(self, analysis: ImageAnalysis, spec: CaptionSpec) -> str:
        return "caption"


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
async def test_e2e_preview_includes_expanded_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_config()
    storage = DummyStorage(cfg.dropbox)
    ai = AIService(DummyAnalyzer(), DummyGenerator(cfg.openai))
    orchestrator = WorkflowOrchestrator(config=cfg, storage=storage, ai_service=ai, publishers=[])
    # Ensure dedup state does not block the test
    monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
    monkeypatch.setattr("publisher_v2.core.workflow.save_posted_hash", lambda h: None)
    result = await orchestrator.execute(preview_mode=True)
    assert result.image_analysis is not None
    analysis = result.image_analysis
    assert getattr(analysis, "subject", None)
    assert getattr(analysis, "style", None)
    assert getattr(analysis, "lighting", None)
    assert getattr(analysis, "camera", None)
    assert getattr(analysis, "clothing_or_accessories", None)
    assert getattr(analysis, "aesthetic_terms", None) is not None
    assert getattr(analysis, "pose", None)
    assert getattr(analysis, "composition", None)
    assert getattr(analysis, "background", None)
    assert getattr(analysis, "color_palette", None)


