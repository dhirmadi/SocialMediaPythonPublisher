from __future__ import annotations

import pytest
from caption_pipeline_fakes import (
    BaseDummyAnalyzer,
    BaseDummyGenerator,
    BaseDummyPublisher,
    BaseDummyStorage,
    make_app_config,
)

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
    """Storage that tracks sidecars and archives for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.sidecars = 0
        self.archived = 0

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        self.sidecars += 1

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        self.archived += 1


@pytest.mark.asyncio
async def test_e2e_preview_then_live_sd_caption(monkeypatch: pytest.MonkeyPatch) -> None:
    # Preview phase - use centralized fixtures (QC-001)
    cfg_prev = make_app_config(
        dropbox={"image_folder": "/ImagesToday"},
        storage_paths={"image_folder": "/ImagesToday"},
        content={"archive": True},
    )
    storage_prev = TrackingStorage()
    ai_prev = AIService(BaseDummyAnalyzer(), SDCaptionGenerator(cfg_prev.openai))  # type: ignore[arg-type]
    orch_prev = WorkflowOrchestrator(
        config=cfg_prev,
        storage=storage_prev,  # type: ignore[arg-type]
        ai_service=ai_prev,
        publishers=[BaseDummyPublisher()],  # type: ignore[arg-type, list-item]
    )
    result_prev = await orch_prev.execute(preview_mode=True)
    assert result_prev.image_analysis is not None
    assert getattr(result_prev.image_analysis, "sd_caption", None)
    assert storage_prev.sidecars == 0  # no side effects in preview

    # Live phase - use centralized fixtures (QC-001)
    cfg_live = make_app_config(
        dropbox={"image_folder": "/ImagesToday"},
        storage_paths={"image_folder": "/ImagesToday"},
        content={"archive": True},
    )
    storage_live = TrackingStorage()
    ai_live = AIService(BaseDummyAnalyzer(), SDCaptionGenerator(cfg_live.openai))  # type: ignore[arg-type]
    orch_live = WorkflowOrchestrator(
        config=cfg_live,
        storage=storage_live,  # type: ignore[arg-type]
        ai_service=ai_live,
        publishers=[BaseDummyPublisher()],  # type: ignore[arg-type, list-item]
    )
    await orch_live.execute(preview_mode=False)
    assert storage_live.sidecars == 1
    # With a successful publisher and archive enabled, archive is called
    assert storage_live.archived == 1
