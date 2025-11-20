from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
)
from publisher_v2.web.service import WebImageService


class _DummyStorage:
    def __init__(self) -> None:
        self.images = ["test.jpg"]
        self.sidecar_content: bytes | None = None
        self.list_images_calls = 0

    async def list_images(self, folder: str) -> List[str]:
        self.list_images_calls += 1
        return list(self.images)

    async def get_temporary_link(self, folder: str, filename: str) -> str:
        return f"https://example.com/{filename}"

    async def download_image(self, folder: str, filename: str) -> bytes:
        # crude branching: return image bytes only; sidecars are handled via
        # download_sidecar_if_exists for this change.
        return b"image-bytes"

    async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None:
        # Derive sidecar from image name and return content when present.
        if self.sidecar_content is not None:
            return self.sidecar_content
        return None

    async def get_file_metadata(self, folder: str, filename: str) -> Dict[str, str]:
        return {"id": "file-id", "rev": "file-rev"}

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        self.sidecar_content = text.encode("utf-8")


class _DummyAIService:
    class _DummyAnalyzer:
        async def analyze(self, url_or_bytes: str | bytes) -> Any:
            from publisher_v2.core.models import ImageAnalysis

            return ImageAnalysis(
                description="desc",
                mood="mood",
                tags=["a", "b"],
                nsfw=False,
                safety_labels=[],
            )

    class _DummyGenerator:
        sd_caption_model = "dummy-model"

        async def generate_with_sd(self, analysis: Any, spec: Any) -> Dict[str, str]:
            return {"caption": "caption", "sd_caption": "sd-caption"}

        async def generate(self, analysis: Any, spec: Any) -> str:
            return "caption"

    def __init__(self) -> None:
        self.analyzer = self._DummyAnalyzer()
        self.generator = self._DummyGenerator()

    async def create_caption_pair_from_analysis(self, analysis: Any, spec: Any) -> tuple[str, str | None]:
        # Mirror generate_with_sd behaviour used by the real AIService.
        pair = await self.generator.generate_with_sd(analysis, spec)
        return pair["caption"], pair.get("sd_caption")

    async def create_caption(self, url_or_bytes: str | bytes, spec: Any) -> str:
        analysis = await self.analyzer.analyze(url_or_bytes)
        return await self.generator.generate(analysis, spec)


class _DummyOrchestrator:
    async def execute(self, select_filename: str | None = None, dry_publish: bool = False, preview_mode: bool = False):
        from publisher_v2.core.models import WorkflowResult, PublishResult

        return WorkflowResult(
            success=True,
            image_name=select_filename or "test.jpg",
            caption="caption",
            publish_results={"telegram": PublishResult(success=True, platform="telegram", post_id="1")},
            archived=True,
            error=None,
            correlation_id="cid",
        )


@pytest.fixture
def web_service(monkeypatch: pytest.MonkeyPatch) -> WebImageService:
    # Patch CONFIG_PATH to some dummy value; loader will not be used after we patch attributes.
    import os

    os.environ.setdefault("CONFIG_PATH", "configfiles/fetlife.ini")

    # Provide a minimal in-memory config to avoid depending on a real config file.
    cfg = ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        ),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(telegram_enabled=False, instagram_enabled=False, email_enabled=False),
        telegram=None,
        instagram=None,
        email=None,
        content=ContentConfig(hashtag_string="#tags", archive=True, debug=False),
    )
    monkeypatch.setattr(
        "publisher_v2.web.service.load_application_config",
        lambda config_path, env_path: cfg,
    )

    # Instantiate service, then override heavy collaborators with fakes
    svc = WebImageService()
    svc.storage = _DummyStorage()
    svc.ai_service = _DummyAIService()
    svc.orchestrator = _DummyOrchestrator()
    return svc


@pytest.mark.asyncio
async def test_get_random_image_returns_basic_fields(web_service: WebImageService) -> None:
    img = await web_service.get_random_image()
    assert img.filename == "test.jpg"
    assert img.temp_url.endswith("test.jpg")
    # sha256 may be computed from dummy bytes
    assert img.sha256 is not None


@pytest.mark.asyncio
async def test_get_random_image_uses_sidecar_view_when_present(web_service: WebImageService) -> None:
    storage: _DummyStorage = web_service.storage  # type: ignore[assignment]
    # Pre-populate a sidecar with both sd_caption and metadata caption
    sidecar_text = (
        "sd caption\n"
        "\n"
        "# ---\n"
        "# caption: human caption\n"
    )
    storage.sidecar_content = sidecar_text.encode("utf-8")

    img = await web_service.get_random_image()
    assert img.has_sidecar is True
    assert img.sd_caption == "sd caption"
    # metadata caption should be preferred for display
    assert img.caption == "human caption"


@pytest.mark.asyncio
async def test_get_random_image_uses_cached_image_list(web_service: WebImageService) -> None:
    storage: _DummyStorage = web_service.storage  # type: ignore[assignment]
    storage.list_images_calls = 0

    # First call populates the cache.
    await web_service.get_random_image()
    # Second call should reuse cache and not hit list_images again.
    await web_service.get_random_image()

    assert storage.list_images_calls == 1


@pytest.mark.asyncio
async def test_analyze_and_caption_writes_sidecar(web_service: WebImageService) -> None:
    # Ensure we start without sidecar
    storage: _DummyStorage = web_service.storage  # type: ignore[assignment]
    storage.sidecar_content = None

    res = await web_service.analyze_and_caption("test.jpg")
    assert res.filename == "test.jpg"
    assert res.caption
    assert res.sd_caption
    assert res.sidecar_written is True
    assert storage.sidecar_content is not None


@pytest.mark.asyncio
async def test_publish_image_uses_orchestrator(web_service: WebImageService) -> None:
    res = await web_service.publish_image("test.jpg")
    assert res.filename == "test.jpg"
    assert res.any_success is True
    assert res.archived is True
    assert "telegram" in res.results



