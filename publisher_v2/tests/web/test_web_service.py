from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from publisher_v2.web.service import WebImageService


class _DummyStorage:
    def __init__(self) -> None:
        self.images = ["test.jpg"]
        self.sidecar_content: bytes | None = None

    async def list_images(self, folder: str) -> List[str]:
        return list(self.images)

    async def get_temporary_link(self, folder: str, filename: str) -> str:
        return f"https://example.com/{filename}"

    async def download_image(self, folder: str, filename: str) -> bytes:
        # crude branching: return sidecar for .txt; image bytes otherwise
        if filename.endswith(".txt") and self.sidecar_content is not None:
            return self.sidecar_content
        return b"image-bytes"

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



