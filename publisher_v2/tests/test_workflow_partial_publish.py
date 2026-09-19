"""REL-2/REL-3 (#85): partial publish never archives, never double-posts.

Telegram OK + Instagram failed must leave the image unarchived with a failed
Instagram record; the next run publishes only to Instagram.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from typing import Any

import pytest
from conftest import BaseDummyStorage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
from publisher_v2.db.models import Base
from publisher_v2.db.publish_store import PublishStore
from publisher_v2.services.ai import AIService
from publisher_v2.services.publishers.base import Publisher


@pytest.fixture(autouse=True)
def _isolated_posted_state(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))


@pytest.fixture
async def publish_store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    yield PublishStore(factory)
    await engine.dispose()


class _ArchiveTrackingStorage(BaseDummyStorage):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.archived: list[str] = []

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        self.archived.append(filename)


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


class _ScriptedPublisher(Publisher):
    """Succeeds or fails per instructions; records publish invocations."""

    def __init__(self, name: str, outcomes: list[bool], calls: dict[str, int]) -> None:
        self._name = name
        self._outcomes = outcomes
        self._calls = calls

    @property
    def platform_name(self) -> str:
        return self._name

    def is_enabled(self) -> bool:
        return True

    async def publish(self, image_path: str, caption: str, context: Any = None) -> PublishResult:
        n = self._calls.get(self._name, 0)
        self._calls[self._name] = n + 1
        ok = self._outcomes[min(n, len(self._outcomes) - 1)]
        if ok:
            return PublishResult(success=True, platform=self._name, post_id=f"{self._name}-{n}")
        return PublishResult(success=False, platform=self._name, error="scripted failure")


class _HangingPublisher(Publisher):
    """Never returns before the publish timeout, to exercise the timeout->unknown path."""

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
        await asyncio.sleep(3600)
        raise AssertionError("should have been cancelled by the publish timeout")


class _RaisingPublisher(Publisher):
    """Raises instead of returning a PublishResult, to exercise the failed-mapping path."""

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
        raise ConnectionError("boom at https://example.com/secret-path")


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


async def test_partial_publish_not_archived_then_retries_only_failed(publish_store: PublishStore) -> None:
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [
        _ScriptedPublisher("telegram", [True], calls),
        _ScriptedPublisher("instagram", [False, True], calls),
    ]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    orchestrator = WorkflowOrchestrator(
        _config(), storage, _DummyAI(), publishers, tenant="t1", publish_store=publish_store
    )

    first = await orchestrator.execute()

    assert first.success is False
    assert first.partial is True
    assert first.archived is False
    assert storage.archived == []
    assert calls == {"telegram": 1, "instagram": 1}

    # Instagram row is failed and re-leasable; telegram is published.
    posted = await publish_store.posted_platforms("t1", first.sha256 or "")
    # sha256 not exposed on non-preview results; derive from store contents instead.
    from sqlalchemy import select

    from publisher_v2.db.models import PublishRecord

    async with publish_store._session_factory() as session:  # noqa: SLF001 — test introspection
        rows = (await session.execute(select(PublishRecord))).scalars().all()
    by_platform = {r.platform: r.status for r in rows}
    assert by_platform == {"telegram": "published", "instagram": "failed"}
    content_hash = rows[0].content_hash
    posted = await publish_store.posted_platforms("t1", content_hash)
    assert posted == {"telegram"}

    # Second run: same image still in the folder — only instagram publishes.
    second = await orchestrator.execute()

    assert calls == {"telegram": 1, "instagram": 2}
    assert second.success is True
    assert second.partial is False
    assert second.archived is True
    assert storage.archived == ["test.jpg"]


async def test_second_concurrent_click_publishes_nothing(publish_store: PublishStore) -> None:
    """Simulates the web double-click: platforms already leased publish nothing."""
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [_ScriptedPublisher("telegram", [True], calls)]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    orchestrator = WorkflowOrchestrator(
        _config(), storage, _DummyAI(), publishers, tenant="t1", publish_store=publish_store
    )

    first = await orchestrator.execute(select_filename="test.jpg")
    assert first.success is True
    assert calls == {"telegram": 1}

    # Second click on the same image: telegram already published → no new call.
    second = await orchestrator.execute(select_filename="test.jpg")
    assert calls == {"telegram": 1}
    assert second.success is True  # already published everywhere counts as done


async def test_preview_and_dry_publish_never_touch_the_table(publish_store: PublishStore) -> None:
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [_ScriptedPublisher("telegram", [True], calls)]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    orchestrator = WorkflowOrchestrator(
        _config(), storage, _DummyAI(), publishers, tenant="t1", publish_store=publish_store
    )

    await orchestrator.execute(preview_mode=True, dry_publish=True)
    await orchestrator.execute(dry_publish=True)

    from sqlalchemy import select

    from publisher_v2.db.models import PublishRecord

    async with publish_store._session_factory() as session:  # noqa: SLF001 — test introspection
        rows = (await session.execute(select(PublishRecord))).scalars().all()
    assert rows == []
    assert calls == {}


async def test_publisher_timeout_marks_row_unknown_never_archives_never_auto_retries(
    publish_store: PublishStore,
) -> None:
    """A publisher that hangs past the deadline is marked ``unknown``, not ``failed``.

    ``unknown`` rows are never auto-retried (the upload may have completed
    upstream) and the run must not archive, since not every platform reached
    ``published``.
    """
    # #143: the timeout is injected settings, not a module-level env lookup.
    from publisher_v2.config.runtime_settings import RuntimeSettings

    calls: dict[str, int] = {}
    publishers: list[Publisher] = [
        _ScriptedPublisher("telegram", [True], calls),
        _HangingPublisher("instagram", calls),
    ]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    orchestrator = WorkflowOrchestrator(
        _config(),
        storage,
        _DummyAI(),
        publishers,
        tenant="t1",
        publish_store=publish_store,
        settings=RuntimeSettings(publish_timeout_seconds=0.05),
    )

    result = await orchestrator.execute()

    assert result.success is False
    assert result.partial is True
    assert result.archived is False
    assert storage.archived == []
    assert result.publish_results["instagram"].error == "publish timeout"

    from sqlalchemy import select

    from publisher_v2.db.models import PublishRecord

    async with publish_store._session_factory() as session:  # noqa: SLF001 — test introspection
        rows = (await session.execute(select(PublishRecord))).scalars().all()
    by_platform = {r.platform: r.status for r in rows}
    assert by_platform == {"telegram": "published", "instagram": "unknown"}

    # unknown rows are never auto-retried: a second run must not re-publish instagram.
    second = await orchestrator.execute()
    assert calls == {"telegram": 1, "instagram": 1}
    assert second.archived is False


async def test_publisher_exception_marks_row_failed_with_sanitized_message(
    publish_store: PublishStore,
) -> None:
    """A publisher raising an exception is mapped to ``failed`` with a sanitized, non-duplicated message."""
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [
        _ScriptedPublisher("telegram", [True], calls),
        _RaisingPublisher("instagram", calls),
    ]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    orchestrator = WorkflowOrchestrator(
        _config(), storage, _DummyAI(), publishers, tenant="t1", publish_store=publish_store
    )

    result = await orchestrator.execute()

    assert result.success is False
    assert result.partial is True
    assert result.archived is False

    error = result.publish_results["instagram"].error
    assert error is not None
    # sanitize_publisher_error() prepends the type name exactly once (not duplicated)
    # and strips the embedded URL.
    assert error.count("ConnectionError") == 1
    assert error.startswith("ConnectionError: boom at ")
    assert "example.com" not in error

    from sqlalchemy import select

    from publisher_v2.db.models import PublishRecord

    async with publish_store._session_factory() as session:  # noqa: SLF001 — test introspection
        rows = (await session.execute(select(PublishRecord))).scalars().all()
    by_platform = {r.platform: r.status for r in rows}
    assert by_platform == {"telegram": "published", "instagram": "failed"}
    failed_row = next(r for r in rows if r.platform == "instagram")
    assert failed_row.error == error


# --- #139: lease lifecycle around the AI stage ---


class _CountingAnalyzer:
    def __init__(self, fail: bool = False, delay: float = 0.0) -> None:
        self.calls = 0
        self._fail = fail
        self._delay = delay

    async def analyze(self, url_or_bytes: str | bytes) -> Any:
        from publisher_v2.core.models import ImageAnalysis

        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._fail:
            raise RuntimeError("vision exploded")
        return ImageAnalysis(description="Test", mood="neutral", tags=["t"], nsfw=False, safety_labels=[]), None


class _CountingAI(_DummyAI):
    def __init__(self, analyzer: _CountingAnalyzer) -> None:
        super().__init__()
        self.analyzer = analyzer  # type: ignore[assignment]


async def _lease_rows(publish_store: PublishStore) -> list[Any]:
    from sqlalchemy import select

    from publisher_v2.db.models import PublishRecord

    async with publish_store._session_factory() as session:  # noqa: SLF001 — test introspection
        return list((await session.execute(select(PublishRecord))).scalars().all())


IMAGE_SHA256 = hashlib.sha256(b"\x89PNG\r\n\x1a\n").hexdigest()


class _LeaseProbingAnalyzer(_CountingAnalyzer):
    """Asks the store, mid-AI-stage, whether the platform is still leasable."""

    def __init__(self, store: PublishStore, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._store = store
        self.probe: dict[str, object] | None = None

    async def analyze(self, url_or_bytes: str | bytes) -> Any:
        self.probe = await self._store.acquire_lease("t2", IMAGE_SHA256, ["telegram"])
        return await super().analyze(url_or_bytes)


async def test_lease_is_already_held_while_the_ai_stage_runs(publish_store: PublishStore) -> None:
    """#139: lease acquisition moves before the AI stage, so a rival run is blocked during it."""
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [_ScriptedPublisher("telegram", [True], calls)]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    analyzer = _LeaseProbingAnalyzer(publish_store)
    orchestrator = WorkflowOrchestrator(
        _config(), storage, _CountingAI(analyzer), publishers, tenant="t2", publish_store=publish_store
    )

    await orchestrator.execute(select_filename="test.jpg")

    assert analyzer.probe == {}


async def test_ai_stage_failure_leaves_no_leased_row_behind(publish_store: PublishStore) -> None:
    """#139: a lease taken before a crashing AI stage must be released, not wedged."""
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [_ScriptedPublisher("telegram", [True], calls)]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    analyzer = _LeaseProbingAnalyzer(publish_store, fail=True)
    orchestrator = WorkflowOrchestrator(
        _config(), storage, _CountingAI(analyzer), publishers, tenant="t2", publish_store=publish_store
    )

    with pytest.raises(RuntimeError):
        await orchestrator.execute(select_filename="test.jpg")

    assert analyzer.probe == {}, "the lease was held when the AI stage ran"
    rows = await _lease_rows(publish_store)
    assert [r.status for r in rows if r.status == "leased"] == []
    assert calls == {}


async def test_next_run_publishes_after_an_ai_stage_crash(publish_store: PublishStore) -> None:
    """#139 AC: no permanent wedge — the retry run publishes normally."""
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [_ScriptedPublisher("telegram", [True], calls)]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    crashing = WorkflowOrchestrator(
        _config(),
        storage,
        _CountingAI(_CountingAnalyzer(fail=True)),
        publishers,
        tenant="t1",
        publish_store=publish_store,
    )
    with pytest.raises(RuntimeError):
        await crashing.execute(select_filename="test.jpg")

    healthy = WorkflowOrchestrator(
        _config(), storage, _CountingAI(_CountingAnalyzer()), publishers, tenant="t1", publish_store=publish_store
    )
    result = await healthy.execute(select_filename="test.jpg")

    assert result.success is True
    assert calls == {"telegram": 1}


async def test_double_click_costs_exactly_one_ai_stage(publish_store: PublishStore) -> None:
    """#139 AC: the second concurrent click must not pay for vision + captioning."""
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [_ScriptedPublisher("telegram", [True], calls)]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    analyzer = _CountingAnalyzer(delay=0.05)
    orchestrator = WorkflowOrchestrator(
        _config(), storage, _CountingAI(analyzer), publishers, tenant="t1", publish_store=publish_store
    )

    await asyncio.gather(
        orchestrator.execute(select_filename="test.jpg"),
        orchestrator.execute(select_filename="test.jpg"),
    )

    assert analyzer.calls == 1
    assert calls == {"telegram": 1}


# --- #139: file-based fallback when no publish store exists ---


async def test_no_store_selected_file_is_blocked_after_it_was_posted(tmp_path, monkeypatch) -> None:
    """Legacy (SHA256-only) path: a second publish of the same file must not repost."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [_ScriptedPublisher("telegram", [True], calls)]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    orchestrator = WorkflowOrchestrator(_config(), storage, _DummyAI(), publishers, tenant="t1")

    first = await orchestrator.execute(select_filename="test.jpg")
    assert first.success is True

    second = await orchestrator.execute(select_filename="test.jpg")

    assert second.success is False
    assert second.error == "Already published: test.jpg"
    assert calls == {"telegram": 1}


async def test_no_store_preview_of_a_posted_file_is_still_allowed(tmp_path, monkeypatch) -> None:
    """``--select X --preview`` publishes nothing, so posted state must not veto it."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [_ScriptedPublisher("telegram", [True], calls)]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    orchestrator = WorkflowOrchestrator(_config(), storage, _DummyAI(), publishers, tenant="t1")
    await orchestrator.execute(select_filename="test.jpg")

    preview = await orchestrator.execute(select_filename="test.jpg", preview_mode=True)
    dry = await orchestrator.execute(select_filename="test.jpg", dry_publish=True)

    assert preview.error is None, preview.error
    assert dry.error is None, dry.error
    assert calls == {"telegram": 1}


async def test_cancelled_run_still_releases_its_lease(publish_store: PublishStore) -> None:
    """#139: a client disconnect mid-AI-stage must not wedge the lease either."""
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [_ScriptedPublisher("telegram", [True], calls)]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    orchestrator = WorkflowOrchestrator(
        _config(),
        storage,
        _CountingAI(_CountingAnalyzer(delay=5.0)),
        publishers,
        tenant="t1",
        publish_store=publish_store,
    )

    task = asyncio.create_task(orchestrator.execute(select_filename="test.jpg"))
    await asyncio.sleep(0.05)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.05)  # let the shielded release finish

    rows = await _lease_rows(publish_store)
    assert [r.status for r in rows if r.status == "leased"] == []
    assert calls == {}


async def test_a_cancelled_run_stays_cancelled(publish_store: PublishStore) -> None:
    """#139: the release is shielded, the cancellation is not swallowed.

    The window is narrow on purpose: the second cancel lands while the shielded
    release is in flight, which is exactly when the old
    ``contextlib.suppress(CancelledError)`` turned an aborted run into an
    ordinary WorkflowResult — so an outer ``asyncio.timeout`` around
    ``execute()`` would never fire.
    """
    publishers: list[Publisher] = [_ScriptedPublisher("telegram", [True], {})]
    orchestrator = WorkflowOrchestrator(
        _config(),
        _ArchiveTrackingStorage(images=["test.jpg"]),
        _CountingAI(_CountingAnalyzer(delay=5.0)),
        publishers,
        tenant="t1",
        publish_store=publish_store,
    )

    releasing = asyncio.Event()
    original_mark = publish_store.mark

    async def _slow_mark(*args: Any, **kwargs: Any) -> bool:
        releasing.set()
        await asyncio.sleep(0.2)
        return await original_mark(*args, **kwargs)

    publish_store.mark = _slow_mark  # type: ignore[method-assign]

    task = asyncio.create_task(orchestrator.execute(select_filename="test.jpg"))
    await asyncio.sleep(0.05)
    task.cancel()
    await releasing.wait()
    task.cancel()  # lands while the shielded release is running

    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled(), "the run reported a normal result after being cancelled"
    publish_store.mark = original_mark  # type: ignore[method-assign]
    rows = await _lease_rows(publish_store)
    assert [r.status for r in rows if r.status == "leased"] == [], "the lease was still released"


class _RecordingCaptionStore:
    def __init__(self) -> None:
        self.batches: list[dict[str, str]] = []

    async def save_captions_batch(self, *, captions_by_platform: dict[str, str], **_kwargs: Any) -> int:
        self.batches.append(captions_by_platform)
        return len(captions_by_platform)


async def test_skipped_ai_stage_writes_no_empty_caption_history(publish_store: PublishStore) -> None:
    """#139: a run that owns nothing skips the AI stage — it must not store blank captions."""
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [_ScriptedPublisher("telegram", [True], calls)]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    caption_store = _RecordingCaptionStore()
    orchestrator = WorkflowOrchestrator(
        _config(),
        storage,
        _DummyAI(),
        publishers,
        tenant="t1",
        publish_store=publish_store,
        caption_store=caption_store,  # type: ignore[arg-type]
    )

    await orchestrator.execute(select_filename="test.jpg")
    assert caption_store.batches == [{"telegram": "hello world"}]

    await orchestrator.execute(select_filename="test.jpg")  # everything already published

    assert caption_store.batches == [{"telegram": "hello world"}]


async def test_lease_held_past_its_ttl_is_not_released_by_the_aborting_run(
    publish_store: PublishStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#139: another run may already own the reclaimed lease — do not mark it failed."""
    from publisher_v2.config.runtime_settings import load_runtime_settings

    # #143 replaced the module-level _publish_lease_ttl_seconds() this used to
    # monkeypatch: the TTL now comes from the settings the orchestrator was built
    # with, so it is injected rather than patched.
    settings = load_runtime_settings().model_copy(update={"publish_lease_ttl_seconds": 0.0})
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [_ScriptedPublisher("telegram", [True], calls)]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    orchestrator = WorkflowOrchestrator(
        _config(),
        storage,
        _CountingAI(_CountingAnalyzer(fail=True)),
        publishers,
        tenant="t1",
        publish_store=publish_store,
        settings=settings,
    )

    with pytest.raises(RuntimeError):
        await orchestrator.execute(select_filename="test.jpg")

    rows = await _lease_rows(publish_store)
    assert [r.status for r in rows] == ["leased"]


async def test_a_stalled_run_cannot_mark_a_lease_that_was_reclaimed(publish_store: PublishStore) -> None:
    """#139: the orchestrator must pass its lease token down to every mark.

    Run A stalls past the TTL, run B reclaims the lease and starts publishing.
    A's failure mark must not land — it would flip the row to ``failed``, make
    it re-leasable mid-publish, and let a third run post the same image again.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update as sa_update

    from publisher_v2.db.models import PublishRecord

    lease_hash = hashlib.sha256(b"an-image").hexdigest()
    run_a = WorkflowOrchestrator(
        _config(),
        _ArchiveTrackingStorage(images=["test.jpg"]),
        _DummyAI(),
        [],
        tenant="t1",
        publish_store=publish_store,
    )
    publishers: list[Publisher] = [_ScriptedPublisher("telegram", [True], {})]
    await run_a._claim_publish_targets(lease_hash, publishers, {}, "cid-a")

    # A stalls; its lease lapses and run B takes it over.
    engine_factory = publish_store._session_factory
    async with engine_factory() as session:
        await session.execute(sa_update(PublishRecord).values(leased_at=datetime.now(UTC) - timedelta(seconds=7200)))
        await session.commit()
    run_b_owned = await publish_store.acquire_lease("t1", lease_hash, ["telegram"])
    assert set(run_b_owned) == {"telegram"}

    # A finally wakes up and reports its failure.
    await run_a._mark_publish(lease_hash, "telegram", "failed", error="stalled")

    async with engine_factory() as session:
        from sqlalchemy import select

        row = (await session.execute(select(PublishRecord))).scalars().one()
    assert row.status == "leased", "run A reopened a lease that run B was still holding"
