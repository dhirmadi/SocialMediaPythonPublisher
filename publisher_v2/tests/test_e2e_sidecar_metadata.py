from __future__ import annotations

import pytest

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
    CaptionFileConfig,
)
from publisher_v2.core.models import ImageAnalysis, CaptionSpec
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI

# Use centralized test fixtures from conftest.py (QC-001)
from conftest import BaseDummyStorage, BaseDummyAnalyzer, BaseDummyGenerator, BaseDummyPublisher


class MetadataAnalyzer(BaseDummyAnalyzer):
    """Analyzer returning extended fields for sidecar metadata testing."""
    def __init__(self) -> None:
        # Base extended_fields, but customize to match expected metadata
        super().__init__()

    async def analyze(self, url_or_bytes: str | bytes) -> ImageAnalysis:
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
        )


class MetadataGenerator(BaseDummyGenerator):
    """Generator that supports SD caption with sidecar-relevant output."""
    def __init__(self, cfg: OpenAIConfig) -> None:
        super().__init__(
            caption="normal caption",
            sd_caption="fine-art figure study, standing, low-key lighting, studio portrait"
        )
        self.model = cfg.caption_model
        self.sd_caption_model = "gpt-4o-mini"

    async def generate_with_sd(self, analysis: ImageAnalysis, spec: CaptionSpec) -> dict[str, str]:
        return {"caption": self._caption, "sd_caption": self._sd_caption}

    async def generate(self, analysis: ImageAnalysis, spec: CaptionSpec) -> str:
        return "legacy caption"


class SidecarTrackingStorage(BaseDummyStorage):
    """Storage that captures sidecar text for assertions."""
    def __init__(self) -> None:
        super().__init__()
        self.sidecar_text: str | None = None

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        self.sidecar_text = text


def make_config(extended: bool, artist_alias: str | None = None) -> ApplicationConfig:
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
    captionfile = CaptionFileConfig(extended_metadata_enabled=extended, artist_alias=artist_alias)
    return ApplicationConfig(dropbox=drop, openai=openai, platforms=platforms, content=content, captionfile=captionfile)


@pytest.mark.asyncio
@pytest.mark.parametrize("extended", [False, True])
async def test_e2e_sidecar_metadata_content(extended: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = make_config(extended=extended)
    # Use centralized fixtures (QC-001)
    storage = SidecarTrackingStorage()
    ai = AIService(MetadataAnalyzer(), MetadataGenerator(cfg.openai))
    orch = WorkflowOrchestrator(config=cfg, storage=storage, ai_service=ai, publishers=[BaseDummyPublisher()])
    # Bypass dedup state
    monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
    monkeypatch.setattr("publisher_v2.core.workflow.save_posted_hash", lambda h: None)

    result = await orch.execute(preview_mode=False)
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
    cfg = make_config(extended=False, artist_alias="Eoel")
    # Use centralized fixtures (QC-001)
    storage = SidecarTrackingStorage()
    ai = AIService(MetadataAnalyzer(), MetadataGenerator(cfg.openai))
    orch = WorkflowOrchestrator(config=cfg, storage=storage, ai_service=ai, publishers=[BaseDummyPublisher()])
    # Bypass dedup state
    monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
    monkeypatch.setattr("publisher_v2.core.workflow.save_posted_hash", lambda h: None)

    result = await orch.execute(preview_mode=False)
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
    cfg = make_config(extended=False, artist_alias=None)
    # Use centralized fixtures (QC-001)
    storage = SidecarTrackingStorage()
    ai = AIService(MetadataAnalyzer(), MetadataGenerator(cfg.openai))
    orch = WorkflowOrchestrator(config=cfg, storage=storage, ai_service=ai, publishers=[BaseDummyPublisher()])
    # Bypass dedup state
    monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
    monkeypatch.setattr("publisher_v2.core.workflow.save_posted_hash", lambda h: None)

    result = await orch.execute(preview_mode=False)
    assert storage.sidecar_text is not None
    text = storage.sidecar_text or ""
    # Verify artist_alias is NOT present
    assert "artist_alias" not in text
    # Other Phase 1 fields should still be present
    assert "# image_file:" in text
    assert "# sha256:" in text


