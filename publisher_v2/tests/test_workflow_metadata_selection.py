from __future__ import annotations

from types import SimpleNamespace

import pytest

from publisher_v2.config.schema import (
    ApplicationConfig,
    CaptionFileConfig,
    ContentConfig,
    DropboxConfig,
    FeaturesConfig,
    OpenAIConfig,
    PlatformsConfig,
)
from publisher_v2.core.models import ImageAnalysis, PublishResult
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.publishers.base import Publisher


class _MetadataStorage:
    def __init__(self) -> None:
        self.client = object()
        self.images_with_hashes: list[tuple[str, str]] = []
        self.download_map: dict[str, bytes] = {}
        self.temp_link = "https://temp"
        self.sidecar_raise = False
        self.archived = False

    async def list_images_with_hashes(self, folder: str):
        return list(self.images_with_hashes)

    async def list_images(self, folder: str):
        return [name for name, _ in self.images_with_hashes]

    async def download_image(self, folder: str, filename: str) -> bytes:
        return self.download_map[filename]

    async def get_temporary_link(self, folder: str, filename: str) -> str:
        return self.temp_link

    async def get_file_metadata(self, folder: str, filename: str) -> dict[str, str]:
        return {"id": "file", "rev": "1"}

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        if self.sidecar_raise:
            raise RuntimeError("sidecar upload fail")

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        self.archived = True


class _StubAnalyzer:
    async def analyze(self, link: str) -> ImageAnalysis:
        return ImageAnalysis(
            description="desc",
            mood="calm",
            tags=["tag"],
            nsfw=False,
            safety_labels=[],
        )


class _StubAI:
    def __init__(self) -> None:
        self.analyzer = _StubAnalyzer()
        self.generator = SimpleNamespace(sd_caption_model="gpt-4o")

    async def create_caption_pair_from_analysis(self, analysis, spec):
        return "caption", "sd caption"


class _SuccessPublisher(Publisher):
    @property
    def platform_name(self) -> str:
        return "stub"

    def is_enabled(self) -> bool:
        return True

    async def publish(self, image_path: str, caption: str, context: dict | None = None) -> PublishResult:
        return PublishResult(success=True, platform=self.platform_name)


def _build_config() -> ApplicationConfig:
    drop = DropboxConfig(
        app_key="k",
        app_secret="s",
        refresh_token="r",
        image_folder="/Photos",
        archive_folder="archive",
    )
    openai = OpenAIConfig(api_key="sk-test", vision_model="gpt-4o", caption_model="gpt-4o-mini")
    platforms = PlatformsConfig(telegram_enabled=False, instagram_enabled=False, email_enabled=False)
    content = ContentConfig(hashtag_string="#tag", archive=True, debug=False)
    features = FeaturesConfig()
    captionfile = CaptionFileConfig(extended_metadata_enabled=False, artist_alias="artist")
    return ApplicationConfig(
        dropbox=drop,
        openai=openai,
        platforms=platforms,
        features=features,
        content=content,
        captionfile=captionfile,
    )


def _make_orchestrator(storage: _MetadataStorage, publishers: list[Publisher] | None = None) -> WorkflowOrchestrator:
    cfg = _build_config()
    ai_service = _StubAI()  # type: ignore[arg-type]
    return WorkflowOrchestrator(cfg, storage, ai_service, publishers or [])


@pytest.mark.asyncio
async def test_metadata_selection_no_images(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _MetadataStorage()
    storage.images_with_hashes = []

    monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
    monkeypatch.setattr("publisher_v2.core.workflow.load_posted_content_hashes", lambda: set())

    orchestrator = _make_orchestrator(storage)
    result = await orchestrator.execute()
    assert result.success is False
    assert result.error == "No images found"


@pytest.mark.asyncio
async def test_metadata_selection_fast_path_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _MetadataStorage()
    storage.images_with_hashes = [("one.jpg", "dbhash1")]
    storage.download_map["one.jpg"] = b"blob"

    monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: {"h1"})
    monkeypatch.setattr("publisher_v2.core.workflow.load_posted_content_hashes", lambda: {"dbhash1"})

    orchestrator = _make_orchestrator(storage)
    result = await orchestrator.execute()
    assert result.success is False
    assert "No new images to post" in (result.error or "")


@pytest.mark.asyncio
async def test_metadata_selection_specific_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _MetadataStorage()
    storage.images_with_hashes = [("one.jpg", "dbhash1")]
    storage.download_map["one.jpg"] = b"blob"

    monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
    monkeypatch.setattr("publisher_v2.core.workflow.load_posted_content_hashes", lambda: set())

    orchestrator = _make_orchestrator(storage)
    result = await orchestrator.execute(select_filename="missing.jpg")
    assert result.success is False
    assert "Selected file not found" in (result.error or "")


@pytest.mark.asyncio
async def test_metadata_sidecar_error_path(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _MetadataStorage()
    storage.images_with_hashes = [("one.jpg", "dbhash1")]
    storage.download_map["one.jpg"] = b"blob"
    storage.sidecar_raise = True

    save_hashes: list[str] = []
    save_content: list[str] = []
    monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
    monkeypatch.setattr("publisher_v2.core.workflow.load_posted_content_hashes", lambda: set())
    monkeypatch.setattr("publisher_v2.core.workflow.save_posted_hash", lambda value: save_hashes.append(value))
    monkeypatch.setattr(
        "publisher_v2.core.workflow.save_posted_content_hash",
        lambda value: save_content.append(value),
    )

    def _raise_chmod(*_args, **_kwargs):
        raise PermissionError("chmod fail")

    def _raise_unlink(*_args, **_kwargs):
        raise OSError("unlink fail")

    monkeypatch.setattr("publisher_v2.core.workflow.os.chmod", _raise_chmod)
    monkeypatch.setattr("publisher_v2.core.workflow.os.unlink", _raise_unlink)

    orchestrator = _make_orchestrator(storage, [ _SuccessPublisher() ])
    result = await orchestrator.execute()

    assert result.success is True
    assert storage.archived is True
    assert save_hashes and save_content

