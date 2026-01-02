from __future__ import annotations

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
from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI

# Use centralized test fixtures from conftest.py (QC-001)
from conftest import BaseDummyStorage, BaseDummyAnalyzer, BaseDummyGenerator, BaseDummyPublisher


class SDCaptionGenerator(BaseDummyGenerator):
    """Generator that supports SD caption generation."""
    def __init__(self, cfg: OpenAIConfig) -> None:
        super().__init__(caption="normal caption", sd_caption="fine-art portrait, soft light, calm mood")
        self.model = cfg.caption_model

    async def generate_with_sd(self, analysis: ImageAnalysis, spec: CaptionSpec) -> dict[str, str]:
        return {"caption": self._caption, "sd_caption": self._sd_caption}

    async def generate(self, analysis: ImageAnalysis, spec: CaptionSpec) -> str:
        return "legacy caption"


class TrackingStorage(BaseDummyStorage):
    """Storage that tracks sidecars and archives for assertions."""
    def __init__(self) -> None:
        super().__init__()
        self.sidecars = 0
        self.archived = 0

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        self.sidecars += 1

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        self.archived += 1


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
async def test_e2e_preview_then_live_sd_caption(monkeypatch: pytest.MonkeyPatch) -> None:
    # Bypass dedup state
    monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
    monkeypatch.setattr("publisher_v2.core.workflow.save_posted_hash", lambda h: None)
    
    # Preview phase - use centralized fixtures (QC-001)
    cfg_prev = make_config(archive=True)
    storage_prev = TrackingStorage()
    ai_prev = AIService(BaseDummyAnalyzer(), SDCaptionGenerator(cfg_prev.openai))
    orch_prev = WorkflowOrchestrator(config=cfg_prev, storage=storage_prev, ai_service=ai_prev, publishers=[BaseDummyPublisher()])
    result_prev = await orch_prev.execute(preview_mode=True)
    assert result_prev.image_analysis is not None
    assert getattr(result_prev.image_analysis, "sd_caption", None)
    assert storage_prev.sidecars == 0  # no side effects in preview

    # Live phase - use centralized fixtures (QC-001)
    cfg_live = make_config(archive=True)
    storage_live = TrackingStorage()
    ai_live = AIService(BaseDummyAnalyzer(), SDCaptionGenerator(cfg_live.openai))
    orch_live = WorkflowOrchestrator(config=cfg_live, storage=storage_live, ai_service=ai_live, publishers=[BaseDummyPublisher()])
    result_live = await orch_live.execute(preview_mode=False)
    assert storage_live.sidecars == 1
    # With a successful publisher and archive enabled, archive is called
    assert storage_live.archived == 1


