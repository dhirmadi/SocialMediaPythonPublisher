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
from conftest import BaseDummyStorage, BaseDummyAnalyzer, BaseDummyGenerator


class ExpandedFieldsAnalyzer(BaseDummyAnalyzer):
    """Analyzer that returns extended fields for expanded analysis tests."""
    def __init__(self) -> None:
        super().__init__(extended_fields=True)


class FixedCaptionGenerator(BaseDummyGenerator):
    """Generator that returns a fixed caption."""
    def __init__(self, cfg: OpenAIConfig) -> None:
        super().__init__(caption="caption")
        self.model = cfg.caption_model


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
    # Use centralized fixtures (QC-001)
    storage = BaseDummyStorage()
    ai = AIService(ExpandedFieldsAnalyzer(), FixedCaptionGenerator(cfg.openai))
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


