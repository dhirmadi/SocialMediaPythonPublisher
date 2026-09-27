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

from caption_pipeline_fakes import BaseDummyStorage, make_app_config, stub_ai_service

from publisher_v2.config.runtime_settings import RuntimeSettings
from publisher_v2.core.models import PublishResult
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.db.publish_store import PublishStore
from publisher_v2.services.publishers.base import Publisher


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

    orchestrator = WorkflowOrchestrator(
        make_app_config(content={"archive": True}),
        storage,
        stub_ai_service(),
        publishers,
        tenant="t1",
        publish_store=store,
    )

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
        make_app_config(content={"archive": True}),
        storage,
        stub_ai_service(),
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

    orchestrator = WorkflowOrchestrator(
        make_app_config(content={"archive": True}),
        storage,
        stub_ai_service(),
        publishers,
        tenant="t1",
        publish_store=None,
    )

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
