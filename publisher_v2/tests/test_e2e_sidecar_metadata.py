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
from publisher_v2.core.models import ImageAnalysis, CaptionSpec, PublishResult
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI
from publisher_v2.services.storage import DropboxStorage
from publisher_v2.services.publishers.base import Publisher


class DummyAnalyzer(VisionAnalyzerOpenAI):
    def __init__(self) -> None:
        pass

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


class DummyGenerator(CaptionGeneratorOpenAI):
    def __init__(self, cfg: OpenAIConfig) -> None:
        super().__init__(cfg)
        self.sd_caption_model = "gpt-4o-mini"

    async def generate_with_sd(self, analysis: ImageAnalysis, spec: CaptionSpec) -> dict[str, str]:
        return {
            "caption": "normal caption",
            "sd_caption": "fine-art figure study, standing, low-key lighting, studio portrait",
        }

    async def generate(self, analysis: ImageAnalysis, spec: CaptionSpec) -> str:
        return "legacy caption"


class DummyStorage(DropboxStorage):
    def __init__(self, cfg: DropboxConfig) -> None:
        self.config = cfg
        self.sidecar_text: str | None = None

    async def list_images(self, folder: str):
        return ["image.jpg"]

    async def download_image(self, folder: str, filename: str) -> bytes:
        return b"data"

    async def get_temporary_link(self, folder: str, filename: str) -> str:
        return "http://tmp"

    async def get_file_metadata(self, folder: str, filename: str):
        return {"id": "id:XYZ", "rev": "123"}

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        self.sidecar_text = text

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        # no-op
        pass


class DummyPublisher(Publisher):
    @property
    def platform_name(self) -> str:
        return "dummy"

    def is_enabled(self) -> bool:
        return True

    async def publish(self, image_path: str, caption: str, context: dict | None = None) -> PublishResult:
        return PublishResult(success=True, platform=self.platform_name)


def make_config(extended: bool) -> ApplicationConfig:
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
    captionfile = CaptionFileConfig(extended_metadata_enabled=extended)
    return ApplicationConfig(dropbox=drop, openai=openai, platforms=platforms, content=content, captionfile=captionfile)


@pytest.mark.asyncio
@pytest.mark.parametrize("extended", [False, True])
async def test_e2e_sidecar_metadata_content(extended: bool) -> None:
    cfg = make_config(extended=extended)
    storage = DummyStorage(cfg.dropbox)
    ai = AIService(DummyAnalyzer(), DummyGenerator(cfg.openai))
    orch = WorkflowOrchestrator(config=cfg, storage=storage, ai_service=ai, publishers=[DummyPublisher()])

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


