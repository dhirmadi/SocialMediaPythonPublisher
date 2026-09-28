from __future__ import annotations

import pytest
from caption_pipeline_fakes import make_app_config

from publisher_v2.config.schema import (
    DropboxConfig,
)
from publisher_v2.core.models import ImageAnalysis, PublishResult
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.services.storage_protocol import FileMetadata


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

    async def get_file_metadata(self, folder: str, filename: str) -> FileMetadata:
        return FileMetadata(file_id="file-id", revision="1", modified_at=None, size=None)

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        self.sidecar_writes += 1

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        self.archives += 1

    def supports_content_hashing(self) -> bool:
        return False


class _StubAnalyzer:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, url_or_bytes: str | bytes) -> tuple[ImageAnalysis, None]:
        self.calls += 1
        return ImageAnalysis(description="desc", mood="calm", tags=["tag"], nsfw=False, safety_labels=[]), None


class _StubGenerator:
    def __init__(self) -> None:
        self.calls = 0
        self.sd_caption_enabled = True
        self.sd_caption_single_call_enabled = True

    async def generate_with_sd(self, analysis: ImageAnalysis, spec) -> tuple[dict[str, str], None]:
        self.calls += 1
        return {"caption": "generated", "sd_caption": "sd style"}, None

    async def generate(self, analysis: ImageAnalysis, spec) -> tuple[str, None]:
        self.calls += 1
        return "fallback", None


class _StubPublisher(Publisher):
    def __init__(self, name: str = "stub") -> None:
        self.called = False
        self.received_caption: str | None = None
        self._name = name

    @property
    def platform_name(self) -> str:
        return self._name

    def is_enabled(self) -> bool:
        return True

    async def publish(self, image_path: str, caption: str, context: dict | None = None) -> PublishResult:
        self.called = True
        self.received_caption = caption
        return PublishResult(success=True, platform=self.platform_name)


def _make_orchestrator(monkeypatch: pytest.MonkeyPatch, publishers: list[Publisher] | None = None):
    cfg = make_app_config(platforms={"telegram_enabled": True}, content={"debug": True})
    assert cfg.dropbox is not None
    storage = _StubStorage(cfg.dropbox)
    analyzer = _StubAnalyzer()
    generator = _StubGenerator()
    ai_service = AIService(analyzer, generator)  # type: ignore[arg-type]
    pubs = publishers or []

    orchestrator = WorkflowOrchestrator(cfg, storage, ai_service, pubs)  # type: ignore[arg-type]
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


# --- Caption override tests ---


@pytest.mark.asyncio
async def test_caption_override_skips_ai_and_uses_provided_caption(monkeypatch: pytest.MonkeyPatch) -> None:
    publisher = _StubPublisher()
    orchestrator, cfg, _, _, generator, _ = _make_orchestrator(monkeypatch, [publisher])
    cfg.content.debug = False

    await orchestrator.execute(caption_override="User approved caption")

    assert generator.calls == 0
    assert publisher.called is True
    assert publisher.received_caption is not None
    assert "User approved caption" in publisher.received_caption


@pytest.mark.parametrize(
    "caption_override",
    [
        pytest.param("", id="caption_override_empty_string_falls_through_to_ai"),
        pytest.param("   ", id="caption_override_whitespace_only_falls_through_to_ai"),
    ],
)
@pytest.mark.asyncio
async def test_caption_override_blank_falls_through_to_ai(monkeypatch: pytest.MonkeyPatch, caption_override) -> None:
    publisher = _StubPublisher()
    orchestrator, cfg, _, _, generator, _ = _make_orchestrator(monkeypatch, [publisher])
    cfg.content.debug = False

    await orchestrator.execute(caption_override=caption_override)

    assert generator.calls >= 1


@pytest.mark.asyncio
async def test_caption_override_is_sanitized_by_format_caption(monkeypatch: pytest.MonkeyPatch) -> None:
    """Override with em-dash and hashtag is sanitized for the email platform."""
    publisher = _StubPublisher(name="email")
    orchestrator, cfg, _, _, generator, _ = _make_orchestrator(monkeypatch, [publisher])
    cfg.content.debug = False
    cfg.platforms.email_enabled = True

    await orchestrator.execute(caption_override="Hello #world \u2014 beautiful day")

    assert generator.calls == 0
    assert publisher.called is True
    assert publisher.received_caption is not None
    assert "#world" not in publisher.received_caption
    assert " - " in publisher.received_caption


@pytest.mark.asyncio
async def test_caption_override_none_preserves_existing_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    publisher = _StubPublisher()
    orchestrator, cfg, _, _, generator, _ = _make_orchestrator(monkeypatch, [publisher])
    cfg.content.debug = False

    result = await orchestrator.execute(caption_override=None)

    assert generator.calls >= 1
    assert publisher.called is True
    assert result.caption != ""
