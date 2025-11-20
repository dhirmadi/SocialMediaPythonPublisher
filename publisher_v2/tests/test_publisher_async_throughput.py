from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List

import pytest

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
)
from publisher_v2.core.models import PublishResult
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.services.storage import DropboxStorage
from publisher_v2.utils.images import ensure_max_width_async


class _DummyStorage(DropboxStorage):
    def __init__(self) -> None:
        self.config = DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        )

    async def list_images(self, folder: str) -> List[str]:
        return ["test.jpg"]

    async def download_image(self, folder: str, filename: str) -> bytes:
        return b"\x89PNG\r\n\x1a\n"

    async def get_temporary_link(self, folder: str, filename: str) -> str:
        return "https://example.com/tmp/test.jpg"

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        return None


class _DummyAnalyzer:
    async def analyze(self, url_or_bytes: str | bytes) -> Any:
        from publisher_v2.core.models import ImageAnalysis

        return ImageAnalysis(
            description="Test image",
            mood="neutral",
            tags=["test"],
            nsfw=False,
            safety_labels=[],
        )


class _DummyGenerator:
    async def generate(self, analysis: Any, spec: Any) -> str:
        return "hello world"


class _DummyAI(AIService):
    def __init__(self) -> None:
        self.analyzer = _DummyAnalyzer()
        self.generator = _DummyGenerator()

        class _NoopLimiter:
            async def __aenter__(self) -> None:  # type: ignore[override]
                return None

            async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[override]
                return False

        self._rate_limiter = _NoopLimiter()


class _SleepingPublisher(Publisher):
    def __init__(self, name: str, delay: float, spans: Dict[str, List[float]]) -> None:
        self._name = name
        self._delay = delay
        self._spans = spans

    @property
    def platform_name(self) -> str:
        return self._name

    def is_enabled(self) -> bool:
        return True

    async def publish(self, image_path: str, caption: str, context: Any = None) -> PublishResult:
        start = time.perf_counter()
        await asyncio.sleep(self._delay)
        end = time.perf_counter()
        self._spans.setdefault(self._name, []).append((start, end))
        return PublishResult(success=True, platform=self._name)


class _LoggingPublisher(Publisher):
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    @property
    def platform_name(self) -> str:
        return "logging-dummy"

    def is_enabled(self) -> bool:
        return True

    async def publish(self, image_path: str, caption: str, context: Any = None) -> PublishResult:
        # Import here to avoid tight coupling at module import time
        from publisher_v2.utils.logging import log_publisher_publish, now_monotonic

        start = now_monotonic()
        await asyncio.sleep(0)
        log_publisher_publish(self._logger, self.platform_name, start, success=True)
        return PublishResult(success=True, platform=self.platform_name)


@pytest.mark.asyncio
async def test_publishers_run_concurrently() -> None:
    cfg = ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        ),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(telegram_enabled=False, instagram_enabled=False, email_enabled=False),
        telegram=None,
        instagram=None,
        email=None,
        content=ContentConfig(hashtag_string="#tags", archive=False, debug=False),
    )

    storage = _DummyStorage()
    ai = _DummyAI()
    spans: Dict[str, List[float]] = {}
    publishers: List[Publisher] = [
        _SleepingPublisher("p1", 0.15, spans),
        _SleepingPublisher("p2", 0.15, spans),
    ]

    orchestrator = WorkflowOrchestrator(cfg, storage, ai, publishers)
    await orchestrator.execute()

    assert "p1" in spans and "p2" in spans
    (p1_start, p1_end) = spans["p1"][0]
    (p2_start, p2_end) = spans["p2"][0]

    # Intervals should overlap if asyncio.gather is running them concurrently.
    assert not (p1_end <= p2_start or p2_end <= p1_start)


@pytest.mark.asyncio
async def test_ensure_max_width_async_delegates_to_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: Dict[str, int] = {"count": 0}

    def _fake_ensure_max_width(path: str, max_width: int = 1280) -> str:
        calls["count"] += 1
        return path

    monkeypatch.setattr("publisher_v2.utils.images.ensure_max_width", _fake_ensure_max_width)
    result = await ensure_max_width_async("image.jpg", max_width=1024)
    assert result == "image.jpg"
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_publisher_publish_emits_structured_log(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("publisher_v2.publishers.test")
    caplog.set_level(logging.INFO, logger="publisher_v2.publishers.test")

    pub = _LoggingPublisher(logger)
    result = await pub.publish("image.jpg", "caption")
    assert result.success is True

    records = [r for r in caplog.records if "publisher_publish" in r.getMessage()]
    assert records, "Expected at least one publisher_publish log entry"


