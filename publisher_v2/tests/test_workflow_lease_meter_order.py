"""PUB-047 AC6 (#185): the lease release runs before any storage-ops metering.

``execute()``'s ``finally`` block must release a still-pending lease (under its
existing ``asyncio.shield``) strictly before it calls ``meter.flush()``. Otherwise a
hung orchestrator flush stalls the release, and a cancellation delivered during that
flush drops the release entirely, leaving the row leased until the TTL expires.

Assertions are on a shared call-order log, never on timing.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any

import pytest
from conftest import BaseDummyStorage

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
)
from publisher_v2.core.exceptions import AIServiceError
from publisher_v2.core.models import PublishResult
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService
from publisher_v2.services.publishers.base import Publisher

LEASE_RELEASE = "lease_release"
METER_FLUSH = "meter_flush"


@pytest.fixture(autouse=True)
def _isolated_posted_state(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))


class _AbortingAnalyzer:
    """Aborts the run after the lease is claimed but before anything is published."""

    async def analyze(self, url_or_bytes: str | bytes) -> Any:
        raise AIServiceError("vision unavailable")


class _AbortingAI(AIService):
    def __init__(self) -> None:
        self.analyzer = _AbortingAnalyzer()  # type: ignore[assignment]

        class _NoopLimiter:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

        self._rate_limiter = _NoopLimiter()  # type: ignore[assignment]


class _NeverPublishes(Publisher):
    """Enabled so the run takes a lease; never actually reached."""

    @property
    def platform_name(self) -> str:
        return "telegram"

    def is_enabled(self) -> bool:
        return True

    async def publish(self, image_path: str, caption: str, context: Any = None) -> PublishResult:
        raise AssertionError("the run aborts before publishing")


class _RecordingStore:
    """Tiny publish-store fake that records the lease release in the shared order log."""

    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.marks: list[tuple[str, str]] = []

    async def posted_platforms(self, tenant: str, content_hash: str) -> set[str]:
        return set()

    async def acquire_lease(self, tenant: str, content_hash: str, platforms: list[str]) -> dict[str, datetime]:
        now = datetime.now(UTC)
        return {platform: now for platform in platforms}

    async def mark(
        self,
        tenant: str,
        content_hash: str,
        platform: str,
        status: str,
        post_id: str | None = None,
        error: str | None = None,
        lease_token: datetime | None = None,
    ) -> None:
        self._order.append(LEASE_RELEASE)
        self.marks.append((platform, status))


class _HangingMeter:
    """Records its flush in the shared order log, then hangs like a dead orchestrator."""

    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.flush_started = asyncio.Event()
        self.flush_calls = 0

    async def flush(self) -> None:
        self.flush_calls += 1
        self._order.append(METER_FLUSH)
        self.flush_started.set()
        await asyncio.Event().wait()  # never resolves; only a cancellation ends it


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


def _build(order: list[str]) -> tuple[WorkflowOrchestrator, _RecordingStore, _HangingMeter]:
    store = _RecordingStore(order)
    meter = _HangingMeter(order)
    orchestrator = WorkflowOrchestrator(
        _config(),
        BaseDummyStorage(images=["test.jpg"]),
        _AbortingAI(),
        [_NeverPublishes()],
        tenant="t1",
        publish_store=store,  # type: ignore[arg-type]
        storage_ops_meter=meter,  # type: ignore[arg-type]
    )
    return orchestrator, store, meter


async def _cancel(task: asyncio.Task[Any]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


async def test_lease_release_happens_before_meter_flush_in_finally() -> None:
    """AC6: the release token is recorded before ``flush()`` is even invoked."""
    order: list[str] = []
    orchestrator, store, meter = _build(order)

    task = asyncio.create_task(orchestrator.execute())
    try:
        await asyncio.wait_for(meter.flush_started.wait(), timeout=5.0)

        assert LEASE_RELEASE in order, (
            f"finally called meter.flush() before releasing the lease; order={order}. "
            "The pending_leases release block must run first."
        )
        assert order.index(LEASE_RELEASE) < order.index(METER_FLUSH), f"wrong order: {order}"
        assert store.marks == [("telegram", "failed")]
    finally:
        await _cancel(task)


async def test_cancellation_during_meter_flush_still_leaves_lease_released() -> None:
    """AC6: cancelling during the hung flush still leaves the lease released, and re-raises."""
    order: list[str] = []
    orchestrator, store, meter = _build(order)

    task = asyncio.create_task(orchestrator.execute())
    await asyncio.wait_for(meter.flush_started.wait(), timeout=5.0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert store.marks == [("telegram", "failed")], (
        f"cancellation during the meter flush dropped the lease release; order={order}"
    )
    assert order.index(LEASE_RELEASE) < order.index(METER_FLUSH), f"wrong order: {order}"
