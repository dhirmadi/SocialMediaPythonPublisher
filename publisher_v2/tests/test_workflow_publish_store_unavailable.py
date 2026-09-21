"""PUB-047 #186 / AC8-AC9: the publish claim fails closed.

AC8: when the publish store raises, or hangs past ``publish_claim_timeout_seconds``,
``_claim_publish_targets`` raises ``PublishStoreUnavailableError`` instead of falling
open to "publish everywhere"; ``execute()`` catches it, invokes no publisher and
returns ``WorkflowResult(success=False, error="publish_store_unavailable")``.

AC9: with no publish store configured, the file-state path is unchanged.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest
from conftest import BaseDummyStorage

from publisher_v2.config.runtime_settings import RuntimeSettings
from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
)
from publisher_v2.core.models import ImageAnalysis, PublishResult
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.db.publish_store import PublishStore
from publisher_v2.services.ai import AIService
from publisher_v2.services.publishers.base import Publisher


@pytest.fixture(autouse=True)
def _isolated_posted_state(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """File-based posted state must not leak between tests (random test order)."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))


class _DummyAnalyzer:
    async def analyze(self, url_or_bytes: str | bytes) -> Any:
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
    """Always succeeds; records every invocation so "nothing published" is provable."""

    def __init__(self, name: str, calls: dict[str, int]) -> None:
        self._name = name
        self._calls = calls

    @property
    def platform_name(self) -> str:
        return self._name

    def is_enabled(self) -> bool:
        return True

    async def publish(self, image_path: str, caption: str, context: Any = None) -> PublishResult:
        self._calls[self._name] = self._calls.get(self._name, 0) + 1
        return PublishResult(success=True, platform=self._name, post_id=f"{self._name}-1")


def _config() -> ApplicationConfig:
    return ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        ),
        storage_paths=StoragePathConfig(image_folder="/Photos"),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(),
        content=ContentConfig(hashtag_string="", archive=True, debug=False),
    )


async def test_acquire_lease_raising_aborts_run_with_publish_store_unavailable() -> None:
    """AC8: a raising store aborts the run instead of publishing everywhere."""
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [
        _RecordingPublisher("telegram", calls),
        _RecordingPublisher("instagram", calls),
    ]
    storage = BaseDummyStorage(images=["test.jpg"])
    store = AsyncMock(spec=PublishStore)
    store.posted_platforms.return_value = set()
    store.acquire_lease.side_effect = RuntimeError("publish store connection reset")

    orchestrator = WorkflowOrchestrator(_config(), storage, _DummyAI(), publishers, tenant="t1", publish_store=store)

    result = await orchestrator.execute()

    assert result.success is False
    assert result.error == "publish_store_unavailable"
    assert result.publish_results == {}
    assert calls == {}, "no publisher may be invoked when the publish store is unavailable"
    assert result.archived is False
    assert storage.archives == 0


async def test_acquire_lease_hanging_past_claim_budget_aborts_run() -> None:
    """AC8: a hanging store is bounded by publish_claim_timeout_seconds, then aborts."""
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [_RecordingPublisher("telegram", calls)]
    storage = BaseDummyStorage(images=["test.jpg"])

    store = AsyncMock(spec=PublishStore)
    store.posted_platforms.return_value = set()

    async def _never_returns(*args: Any, **kwargs: Any) -> dict[str, Any]:
        await asyncio.sleep(999)
        raise AssertionError("should have been bounded by the claim budget")

    store.acquire_lease.side_effect = _never_returns

    orchestrator = WorkflowOrchestrator(
        _config(),
        storage,
        _DummyAI(),
        publishers,
        tenant="t1",
        publish_store=store,
        # A real (small) budget: asyncio.wait_for must fire for real, not be mocked away.
        settings=RuntimeSettings(publish_claim_timeout_seconds=0.05),
    )

    # Outer guard so an unbounded claim fails the test instead of hanging the suite.
    result = await asyncio.wait_for(orchestrator.execute(), timeout=5.0)

    assert result.success is False
    assert result.error == "publish_store_unavailable"
    assert result.publish_results == {}
    assert calls == {}, "no publisher may be invoked when the publish claim times out"
    assert storage.archives == 0


async def test_no_publish_store_configured_behaves_as_before() -> None:
    """AC9: the file-state path is untouched — publish, archive, then no re-publish."""
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [_RecordingPublisher("telegram", calls)]
    storage = BaseDummyStorage(images=["test.jpg"])

    orchestrator = WorkflowOrchestrator(_config(), storage, _DummyAI(), publishers, tenant="t1", publish_store=None)

    first = await orchestrator.execute()

    assert first.success is True
    assert first.error is None
    assert calls == {"telegram": 1}
    assert first.publish_results["telegram"].success is True
    assert first.archived is True
    assert storage.archives == 1

    # The file-based posted state still vetoes a second run on the same image.
    await orchestrator.execute()
    assert calls == {"telegram": 1}
    assert storage.archives == 1
