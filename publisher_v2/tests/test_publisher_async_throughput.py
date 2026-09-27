from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import pytest
from caption_pipeline_fakes import BaseDummyStorage, make_app_config, stub_ai_service

from publisher_v2.core.models import PublishResult
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.publishers.base import Publisher


class _SleepingPublisher(Publisher):
    def __init__(self, name: str, delay: float, spans: dict[str, list[tuple[float, float]]]) -> None:
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
    cfg = make_app_config(content={"hashtag_string": "#tags"})

    storage = BaseDummyStorage()
    ai = stub_ai_service()
    spans: dict[str, list[tuple[float, float]]] = {}
    publishers: list[Publisher] = [
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
async def test_publisher_publish_emits_structured_log(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("publisher_v2.publishers.test")
    caplog.set_level(logging.INFO, logger="publisher_v2.publishers.test")

    pub = _LoggingPublisher(logger)
    result = await pub.publish("image.jpg", "caption")
    assert result.success is True

    records = [r for r in caplog.records if "publisher_publish" in r.getMessage()]
    assert records, "Expected at least one publisher_publish log entry"
