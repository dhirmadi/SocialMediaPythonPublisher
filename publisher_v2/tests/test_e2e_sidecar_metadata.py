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


class MetadataAnalyzer(BaseDummyAnalyzer):
    """Analyzer returning extended fields for sidecar metadata testing."""

    def __init__(self) -> None:
        # Base extended_fields, but customize to match expected metadata
        super().__init__()

    async def analyze(self, url_or_bytes: str | bytes) -> tuple[ImageAnalysis, None]:
        return ImageAnalysis(
            description="desc",
            mood="mood",
            tags=["minimalist", "studio portrait"],
            nsfw=False,
            safety_labels=["safe"],
            lighting="low-key directional softbox",
            pose="standing",
            clothing_or_accessories="rope body-form art styling",
            style="fine-art figure study",
        ), None


class MetadataGenerator(BaseDummyGenerator):
    """Generator that supports SD caption with sidecar-relevant output."""

    def __init__(self, cfg: OpenAIConfig) -> None:
        super().__init__(
            caption="normal caption", sd_caption="fine-art figure study, standing, low-key lighting, studio portrait"
        )
        self.model = cfg.caption_model
        self.sd_caption_model = "gpt-4o-mini"

    async def generate_with_sd(self, analysis: ImageAnalysis, spec: CaptionSpec) -> tuple[dict[str, str], None]:
        return {"caption": self._caption, "sd_caption": self._sd_caption}, None

    async def generate(self, analysis: ImageAnalysis, spec: CaptionSpec) -> tuple[str, None]:
        return "legacy caption", None


class SidecarTrackingStorage(BaseDummyStorage):
    """Storage that captures sidecar text for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.sidecar_text: str | None = None

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        self.sidecar_text = text


@pytest.mark.asyncio
@pytest.mark.parametrize("extended", [False, True])
async def test_e2e_sidecar_metadata_content(extended: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_app_config(
        dropbox={"image_folder": "/ImagesToday"},
        storage_paths={"image_folder": "/ImagesToday"},
        captionfile={"extended_metadata_enabled": extended},
    )
    # Use centralized fixtures (QC-001)
    storage = SidecarTrackingStorage()
    ai = AIService(MetadataAnalyzer(), MetadataGenerator(cfg.openai))  # type: ignore[arg-type]
    orch = WorkflowOrchestrator(config=cfg, storage=storage, ai_service=ai, publishers=[BaseDummyPublisher()])  # type: ignore[arg-type, list-item]

    await orch.execute(preview_mode=False)
    assert storage.sidecar_text is not None
    text = storage.sidecar_text or ""
    # First line is the caption
    first_line = text.splitlines()[0]
    assert first_line.startswith("fine-art")
    # Contains separator and metadata keys
    assert "\n# ---\n" in text
    assert "# image_file:" in text
    assert "# sha256:" in text
    assert "# sd_caption_version:" in text
    assert "# model_version:" in text
    # Phase 2 fields present only when extended=True
    assert ("# lighting:" in text) == extended
    assert ("# pose:" in text) == extended
    assert ("# materials:" in text) == extended
    assert ("# art_style:" in text) == extended
    assert ("# tags:" in text) == extended
    assert ("# moderation:" in text) == extended


@pytest.mark.asyncio
async def test_e2e_sidecar_with_artist_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that artist_alias from config appears in Phase 1 metadata."""
    cfg = make_app_config(
        dropbox={"image_folder": "/ImagesToday"},
        storage_paths={"image_folder": "/ImagesToday"},
        captionfile={"artist_alias": "Eoel"},
    )
    # Use centralized fixtures (QC-001)
    storage = SidecarTrackingStorage()
    ai = AIService(MetadataAnalyzer(), MetadataGenerator(cfg.openai))  # type: ignore[arg-type]
    orch = WorkflowOrchestrator(config=cfg, storage=storage, ai_service=ai, publishers=[BaseDummyPublisher()])  # type: ignore[arg-type, list-item]

    await orch.execute(preview_mode=False)
    assert storage.sidecar_text is not None
    text = storage.sidecar_text or ""
    # Verify artist_alias is present in metadata
    assert "# artist_alias: Eoel" in text
    # Verify other Phase 1 fields present
    assert "# image_file:" in text
    assert "# sha256:" in text


@pytest.mark.asyncio
async def test_e2e_sidecar_without_artist_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that when artist_alias is not set, it does not appear in metadata."""
    cfg = make_app_config(dropbox={"image_folder": "/ImagesToday"}, storage_paths={"image_folder": "/ImagesToday"})
    # Use centralized fixtures (QC-001)
    storage = SidecarTrackingStorage()
    ai = AIService(MetadataAnalyzer(), MetadataGenerator(cfg.openai))  # type: ignore[arg-type]
    orch = WorkflowOrchestrator(config=cfg, storage=storage, ai_service=ai, publishers=[BaseDummyPublisher()])  # type: ignore[arg-type, list-item]

    await orch.execute(preview_mode=False)
    assert storage.sidecar_text is not None
    text = storage.sidecar_text or ""
    # Verify artist_alias is NOT present
    assert "artist_alias" not in text
    # Other Phase 1 fields should still be present
    assert "# image_file:" in text
    assert "# sha256:" in text
