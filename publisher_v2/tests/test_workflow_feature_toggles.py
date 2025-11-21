from __future__ import annotations

import pytest

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    FeaturesConfig,
    OpenAIConfig,
    PlatformsConfig,
)
from publisher_v2.core.models import ImageAnalysis, PublishResult
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService
from publisher_v2.services.publishers.base import Publisher


class _StubStorage:
    def __init__(self, cfg: DropboxConfig) -> None:
        self.cfg = cfg
        self.sidecar_writes = 0
        self.archives = 0

    async def list_images(self, folder: str) -> list[str]:
        return ["test.jpg"]

    async def download_image(self, folder: str, filename: str) -> bytes:
        return b"bytes"

    async def get_temporary_link(self, folder: str, filename: str) -> str:
        return "http://temp-link"

    async def get_file_metadata(self, folder: str, filename: str) -> dict[str, str]:
        return {"id": "file-id", "rev": "1"}

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        self.sidecar_writes += 1

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        self.archives += 1


class _StubAnalyzer:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, url_or_bytes: str | bytes) -> ImageAnalysis:
        self.calls += 1
        return ImageAnalysis(description="desc", mood="calm", tags=["tag"], nsfw=False, safety_labels=[])


class _StubGenerator:
    def __init__(self) -> None:
        self.calls = 0
        self.sd_caption_enabled = True
        self.sd_caption_single_call_enabled = True

    async def generate_with_sd(self, analysis: ImageAnalysis, spec) -> dict[str, str]:
        self.calls += 1
        return {"caption": "generated", "sd_caption": "sd style"}

    async def generate(self, analysis: ImageAnalysis, spec) -> str:
        self.calls += 1
        return "fallback"


class _StubPublisher(Publisher):
    def __init__(self) -> None:
        self.called = False

    @property
    def platform_name(self) -> str:
        return "stub"

    def is_enabled(self) -> bool:
        return True

    async def publish(self, image_path: str, caption: str, context: dict | None = None) -> PublishResult:
        self.called = True
        return PublishResult(success=True, platform=self.platform_name)


def _make_config() -> ApplicationConfig:
    drop = DropboxConfig(
        app_key="k",
        app_secret="s",
        refresh_token="r",
        image_folder="/Photos",
        archive_folder="archive",
    )
    openai = OpenAIConfig(api_key="sk-test", vision_model="gpt-4o", caption_model="gpt-4o-mini")
    platforms = PlatformsConfig(telegram_enabled=True, instagram_enabled=False, email_enabled=False)
    content = ContentConfig(hashtag_string="", archive=False, debug=True)
    features = FeaturesConfig()
    return ApplicationConfig(
        dropbox=drop,
        openai=openai,
        platforms=platforms,
        features=features,
        telegram=None,
        instagram=None,
        email=None,
        content=content,
    )


def _make_orchestrator(monkeypatch: pytest.MonkeyPatch, publishers: list[Publisher] | None = None):
    cfg = _make_config()
    storage = _StubStorage(cfg.dropbox)
    analyzer = _StubAnalyzer()
    generator = _StubGenerator()
    ai_service = AIService(analyzer, generator)  # type: ignore[arg-type]
    pubs = publishers or []

    monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
    monkeypatch.setattr("publisher_v2.core.workflow.save_posted_hash", lambda _h: None)
    monkeypatch.setattr("publisher_v2.core.workflow.load_posted_content_hashes", lambda: set())
    monkeypatch.setattr("publisher_v2.core.workflow.save_posted_content_hash", lambda _h: None)

    orchestrator = WorkflowOrchestrator(cfg, storage, ai_service, pubs)
    return orchestrator, cfg, storage, analyzer, generator, pubs


@pytest.mark.asyncio
async def test_workflow_skips_analysis_and_caption_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator, cfg, storage, analyzer, generator, _ = _make_orchestrator(monkeypatch)
    cfg.features.analyze_caption_enabled = False

    result = await orchestrator.execute()

    assert analyzer.calls == 0
    assert generator.calls == 0
    assert result.caption == ""
    assert storage.sidecar_writes == 0


@pytest.mark.asyncio
async def test_workflow_skips_publish_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    publisher = _StubPublisher()
    orchestrator, cfg, storage, analyzer, generator, _ = _make_orchestrator(monkeypatch, [publisher])
    cfg.features.publish_enabled = False

    result = await orchestrator.execute()

    assert publisher.called is False
    assert result.publish_results == {}
    assert storage.archives == 0


@pytest.mark.asyncio
async def test_workflow_default_toggles_execute_all_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    publisher = _StubPublisher()
    orchestrator, cfg, storage, analyzer, generator, _ = _make_orchestrator(monkeypatch, [publisher])
    cfg.content.debug = False

    result = await orchestrator.execute()

    assert analyzer.calls == 1
    assert generator.calls >= 1
    assert storage.sidecar_writes >= 1
    assert publisher.called is True
    assert result.publish_results

