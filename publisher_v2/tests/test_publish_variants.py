"""REL-1 (#83): per-platform image variants rendered once by the orchestrator.

Publishers must never write to a path they did not create; Telegram gets the
1280-wide variant, Instagram 1080, email the untouched original.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pytest
from conftest import BaseDummyStorage
from PIL import Image

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
)
from publisher_v2.core.models import PublishResult
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService
from publisher_v2.services.publishers.base import Publisher


@pytest.fixture(autouse=True)
def _isolated_posted_state(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Keep posted-image dedup state out of the real user cache."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))


def _png_bytes(width: int = 2000, height: int = 1000) -> bytes:
    buf = BytesIO()
    with Image.new("RGB", (width, height), color="red") as img:
        img.save(buf, format="PNG")
    return buf.getvalue()


class _DummyAnalyzer:
    async def analyze(self, url_or_bytes: str | bytes) -> Any:
        from publisher_v2.core.models import ImageAnalysis

        return ImageAnalysis(description="Test", mood="neutral", tags=["t"], nsfw=False, safety_labels=[]), None


class _DummyGenerator:
    async def generate(self, analysis: Any, spec: Any) -> tuple[str, None]:
        return "hello world", None


class _DummyAI(AIService):
    def __init__(self) -> None:
        self.analyzer = _DummyAnalyzer()  # type: ignore[assignment]
        self.generator = _DummyGenerator()  # type: ignore[assignment]

        class _NoopLimiter:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

        self._rate_limiter = _NoopLimiter()  # type: ignore[assignment]


class _RecordingPublisher(Publisher):
    """Records the path and bytes it was handed at publish time."""

    def __init__(self, name: str, received: dict[str, dict[str, Any]]) -> None:
        self._name = name
        self._received = received

    @property
    def platform_name(self) -> str:
        return self._name

    def is_enabled(self) -> bool:
        return True

    async def publish(self, image_path: str, caption: str, context: Any = None) -> PublishResult:
        with open(image_path, "rb") as f:  # noqa: ASYNC230 — test helper reads a tiny local file
            data = f.read()
        with Image.open(BytesIO(data)) as img:
            width = img.size[0]
        self._received[self._name] = {"path": image_path, "bytes": data, "width": width}
        return PublishResult(success=True, platform=self._name)


def _config() -> ApplicationConfig:
    return ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        ),
        storage_paths=StoragePathConfig(image_folder="/Photos"),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(),
        content=ContentConfig(hashtag_string="", archive=False, debug=False),
    )


async def test_each_publisher_gets_its_own_variant() -> None:
    source = _png_bytes(2000, 1000)
    storage = BaseDummyStorage(images=["test.jpg"], content=source)
    received: dict[str, dict[str, Any]] = {}
    publishers: list[Publisher] = [
        _RecordingPublisher("telegram", received),
        _RecordingPublisher("instagram", received),
        _RecordingPublisher("email", received),
    ]

    orchestrator = WorkflowOrchestrator(_config(), storage, _DummyAI(), publishers)
    result = await orchestrator.execute()

    assert result.success, result.error
    assert received["telegram"]["width"] == 1280
    assert received["instagram"]["width"] == 1080
    # Email has no resize_width_px — it must receive the original bytes.
    assert received["email"]["bytes"] == source
    # Three distinct paths: no publisher shares a mutated file with another.
    paths = {info["path"] for info in received.values()}
    assert len(paths) == 3


async def test_source_temp_file_unchanged_and_variants_cleaned_up() -> None:
    source = _png_bytes(2000, 1000)
    storage = BaseDummyStorage(images=["test.jpg"], content=source)
    received: dict[str, dict[str, Any]] = {}
    publishers: list[Publisher] = [
        _RecordingPublisher("telegram", received),
        _RecordingPublisher("email", received),
    ]

    orchestrator = WorkflowOrchestrator(_config(), storage, _DummyAI(), publishers)
    result = await orchestrator.execute()

    assert result.success, result.error
    # The email publisher read the source path — bytes must be the original.
    assert received["email"]["bytes"] == source
    # All temp files (source + variants) are removed after the run.
    import os

    for info in received.values():
        assert not os.path.exists(info["path"])  # noqa: ASYNC240 — test assertion
