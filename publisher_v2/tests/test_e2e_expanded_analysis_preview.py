from __future__ import annotations

import pytest
from caption_pipeline_fakes import BaseDummyAnalyzer, BaseDummyGenerator, BaseDummyStorage, make_app_config

from publisher_v2.config.schema import (
    OpenAIConfig,
)
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService


class ExpandedFieldsAnalyzer(BaseDummyAnalyzer):
    """Analyzer that returns extended fields for expanded analysis tests."""

    def __init__(self) -> None:
        super().__init__(extended_fields=True)


class FixedCaptionGenerator(BaseDummyGenerator):
    """Generator that returns a fixed caption."""

    def __init__(self, cfg: OpenAIConfig) -> None:
        super().__init__(caption="caption")
        self.model = cfg.caption_model


@pytest.mark.asyncio
async def test_e2e_preview_includes_expanded_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_app_config(dropbox={"image_folder": "/ImagesToday"}, storage_paths={"image_folder": "/ImagesToday"})
    # Use centralized fixtures (QC-001)
    storage = BaseDummyStorage()
    ai = AIService(ExpandedFieldsAnalyzer(), FixedCaptionGenerator(cfg.openai))  # type: ignore[arg-type]
    orchestrator = WorkflowOrchestrator(config=cfg, storage=storage, ai_service=ai, publishers=[])  # type: ignore[arg-type]
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
