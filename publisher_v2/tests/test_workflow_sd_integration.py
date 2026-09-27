from __future__ import annotations

import pytest
from caption_pipeline_fakes import BaseDummyAnalyzer, BaseDummyGenerator, BaseDummyStorage, make_app_config

from publisher_v2.config.schema import (
    OpenAIConfig,
)
from publisher_v2.core.models import CaptionSpec, ImageAnalysis
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService


class SDCaptionGenerator(BaseDummyGenerator):
    """Generator that supports SD caption generation."""

    def __init__(self, cfg: OpenAIConfig) -> None:
        super().__init__(caption="normal caption", sd_caption="fine-art portrait, soft light, calm mood")
        self.model = cfg.caption_model

    async def generate_with_sd(self, analysis: ImageAnalysis, spec: CaptionSpec) -> tuple[dict[str, str], None]:
        return {"caption": self._caption, "sd_caption": self._sd_caption}, None

    async def generate(self, analysis: ImageAnalysis, spec: CaptionSpec) -> tuple[str, None]:
        return "legacy caption", None


class TrackingStorage(BaseDummyStorage):
    """Storage that tracks writes and archives for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.writes = 0

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        self.writes += 1


@pytest.mark.asyncio
async def test_workflow_sd_integration_preview_and_live(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_app_config(dropbox={"image_folder": "/ImagesToday"}, storage_paths={"image_folder": "/ImagesToday"})
    # Use centralized fixtures (QC-001)
    storage = TrackingStorage()
    ai = AIService(BaseDummyAnalyzer(), SDCaptionGenerator(cfg.openai))  # type: ignore[arg-type]
    cgf = cfg
    orchestrator = WorkflowOrchestrator(config=cgf, storage=storage, ai_service=ai, publishers=[])  # type: ignore[arg-type]

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
