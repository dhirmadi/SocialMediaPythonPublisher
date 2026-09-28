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
from caption_pipeline_fakes import BaseDummyStorage, make_app_config, stub_ai_service
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from publisher_v2.core.models import PublishResult
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.db.models import Base
from publisher_v2.db.publish_store import PublishStore
from publisher_v2.services.publishers.base import Publisher


@pytest.fixture
async def publish_store(tmp_path):
    # File-backed on purpose: a CancelledError mid-DB-await invalidates the
    # connection, and with ``:memory:`` (StaticPool) the replacement connection
    # is a brand-new empty database — "no such table" instead of the real result.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'publish.db'}", echo=False)
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


async def test_partial_publish_not_archived_then_retries_only_failed(publish_store: PublishStore) -> None:
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [
        _ScriptedPublisher("telegram", [True], calls),
        _ScriptedPublisher("instagram", [False, True], calls),
    ]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    orchestrator = WorkflowOrchestrator(
        make_app_config(content={"archive": True}),
        storage,
        stub_ai_service(),
        publishers,
        tenant="t1",
        publish_store=publish_store,
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
        make_app_config(content={"archive": True}),
        storage,
        stub_ai_service(),
        publishers,
        tenant="t1",
        publish_store=publish_store,
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
        make_app_config(content={"archive": True}),
        storage,
        stub_ai_service(),
        publishers,
        tenant="t1",
        publish_store=publish_store,
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
        make_app_config(content={"archive": True}),
        storage,
        stub_ai_service(),
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
        make_app_config(content={"archive": True}),
        storage,
        stub_ai_service(),
        publishers,
        tenant="t1",
        publish_store=publish_store,
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
        # Set on entry to analyze(): the run is provably mid-AI-stage (lease held).
        self.started = asyncio.Event()

    async def analyze(self, url_or_bytes: str | bytes) -> Any:
        from publisher_v2.core.models import ImageAnalysis

        self.calls += 1
        self.started.set()
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._fail:
            raise RuntimeError("vision exploded")
        return ImageAnalysis(description="Test", mood="neutral", tags=["t"], nsfw=False, safety_labels=[]), None


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
        make_app_config(content={"archive": True}),
        storage,
        stub_ai_service(analyzer),
        publishers,
        tenant="t2",
        publish_store=publish_store,
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
        make_app_config(content={"archive": True}),
        storage,
        stub_ai_service(analyzer),
        publishers,
        tenant="t2",
        publish_store=publish_store,
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
        make_app_config(content={"archive": True}),
        storage,
        stub_ai_service(_CountingAnalyzer(fail=True)),
        publishers,
        tenant="t1",
        publish_store=publish_store,
    )
    with pytest.raises(RuntimeError):
        await crashing.execute(select_filename="test.jpg")

    healthy = WorkflowOrchestrator(
        make_app_config(content={"archive": True}),
        storage,
        stub_ai_service(_CountingAnalyzer()),
        publishers,
        tenant="t1",
        publish_store=publish_store,
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
        make_app_config(content={"archive": True}),
        storage,
        stub_ai_service(analyzer),
        publishers,
        tenant="t1",
        publish_store=publish_store,
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
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [_ScriptedPublisher("telegram", [True], calls)]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    orchestrator = WorkflowOrchestrator(
        make_app_config(content={"archive": True}), storage, stub_ai_service(), publishers, tenant="t1"
    )

    first = await orchestrator.execute(select_filename="test.jpg")
    assert first.success is True

    second = await orchestrator.execute(select_filename="test.jpg")

    assert second.success is False
    assert second.error == "Already published: test.jpg"
    assert calls == {"telegram": 1}


async def test_no_store_preview_of_a_posted_file_is_still_allowed(tmp_path, monkeypatch) -> None:
    """``--select X --preview`` publishes nothing, so posted state must not veto it."""
    calls: dict[str, int] = {}
    publishers: list[Publisher] = [_ScriptedPublisher("telegram", [True], calls)]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    orchestrator = WorkflowOrchestrator(
        make_app_config(content={"archive": True}), storage, stub_ai_service(), publishers, tenant="t1"
    )
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
    analyzer = _CountingAnalyzer(delay=5.0)
    orchestrator = WorkflowOrchestrator(
        make_app_config(content={"archive": True}),
        storage,
        stub_ai_service(analyzer),
        publishers,
        tenant="t1",
        publish_store=publish_store,
    )

    task = asyncio.create_task(orchestrator.execute(select_filename="test.jpg"))
    # Barrier, not a sleep: cancel only once the run is inside the AI stage.
    await asyncio.wait_for(analyzer.started.wait(), timeout=10)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    # No settle sleep: execute() awaits the shielded release before it re-raises.

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
    analyzer = _CountingAnalyzer(delay=5.0)
    orchestrator = WorkflowOrchestrator(
        make_app_config(content={"archive": True}),
        _ArchiveTrackingStorage(images=["test.jpg"]),
        stub_ai_service(analyzer),
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
    # Barrier, not a sleep: a cancel that lands before the lease exists never
    # reaches mark(), and ``releasing.wait()`` would then hang forever.
    await asyncio.wait_for(analyzer.started.wait(), timeout=10)
    task.cancel()
    await asyncio.wait_for(releasing.wait(), timeout=10)
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
        make_app_config(content={"archive": True}),
        storage,
        stub_ai_service(),
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
        make_app_config(content={"archive": True}),
        storage,
        stub_ai_service(_CountingAnalyzer(fail=True)),
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
        make_app_config(content={"archive": True}),
        _ArchiveTrackingStorage(images=["test.jpg"]),
        stub_ai_service(),
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


# --- PUB-086 (#315): leases committed before a cancellation are still released ---


class _LeaseCommitGate:
    """Parks the run right after the real commit of its first ``leased`` row.

    Wraps ``AsyncSession.commit`` (the class the store's session factory builds).
    The first commit that carries a new ``leased`` PublishRecord runs for real,
    then sets ``committed`` and waits on ``hold``. The test cancels the run while
    it is parked there — a lease row is durably committed, but the claim has not
    returned to the workflow — and then sets ``hold`` so a claim that is allowed
    to finish (shielded) can do so. Every other commit passes straight through.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from publisher_v2.db.models import PublishRecord

        self.committed = asyncio.Event()
        self.hold = asyncio.Event()
        self._fired = False
        original_commit = AsyncSession.commit
        gate = self

        async def _gated_commit(session: AsyncSession) -> None:
            inserts_lease = any(isinstance(obj, PublishRecord) and obj.status == "leased" for obj in session.new)
            await original_commit(session)
            if inserts_lease and not gate._fired:
                gate._fired = True
                gate.committed.set()
                await asyncio.wait_for(gate.hold.wait(), timeout=10)

        monkeypatch.setattr(AsyncSession, "commit", _gated_commit)


class _MarkRecorder:
    """Records every real ``PublishStore.mark`` call (delegating to the original).

    PUB-086 AC7/AC2: the release of a committed lease must be fenced by the lease
    token the claim committed — an unfenced mark (``lease_token=None``) could
    reopen a lease another run reclaimed.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        original_mark = PublishStore.mark
        recorder = self

        async def _recording_mark(
            store: PublishStore,
            tenant: str,
            content_hash: str,
            platform: str,
            status: str,
            post_id: str | None = None,
            error: str | None = None,
            lease_token: Any = None,
        ) -> bool:
            recorder.calls.append((platform, status, lease_token))
            return await original_mark(
                store, tenant, content_hash, platform, status, post_id=post_id, error=error, lease_token=lease_token
            )

        monkeypatch.setattr(PublishStore, "mark", _recording_mark)


def _assert_releases_fenced_by_committed_tokens(recorder: _MarkRecorder, rows: list[Any], platforms: set[str]) -> None:
    """Each committed lease was released by a mark carrying the row's own ``leased_at`` token."""
    by_platform = {r.platform: r for r in rows}
    released = {p for p, status, _ in recorder.calls if status == "failed"}
    assert released == platforms, f"released {sorted(released)}, expected {sorted(platforms)}"
    for platform, status, token in recorder.calls:
        assert status == "failed"
        assert token is not None, f"the release of {platform} was an unfenced mark (lease_token=None)"
        committed = by_platform[platform].leased_at
        if committed.tzinfo is None:
            committed = committed.replace(tzinfo=token.tzinfo)
        assert token == committed, f"the release of {platform} was not fenced by the token the claim committed"


async def _cancel_at_first_lease_commit(task: asyncio.Task[Any], gate: _LeaseCommitGate) -> None:
    await asyncio.wait_for(gate.committed.wait(), timeout=10)
    task.cancel()
    gate.hold.set()  # a shielded claim may now run to completion


async def test_cancel_right_after_a_lease_commit_releases_it(
    publish_store: PublishStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PUB-086 AC1: a cancel landing right after the lease row commits must not wedge it."""
    calls: dict[str, int] = {}
    orchestrator = WorkflowOrchestrator(
        make_app_config(content={"archive": True}),
        _ArchiveTrackingStorage(images=["test.jpg"]),
        stub_ai_service(_CountingAnalyzer(delay=5.0)),
        [_ScriptedPublisher("telegram", [True], calls)],
        tenant="t1",
        publish_store=publish_store,
    )
    gate = _LeaseCommitGate(monkeypatch)

    task = asyncio.create_task(orchestrator.execute(select_filename="test.jpg"))
    await _cancel_at_first_lease_commit(task, gate)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=15)

    rows = await _lease_rows(publish_store)
    assert [r.platform for r in rows] == ["telegram"], "the lease row was committed before the cancel"
    assert [r.status for r in rows if r.status == "leased"] == [], "the committed lease was left wedged"
    assert calls == {}


async def test_cancel_mid_claim_releases_every_committed_lease(
    publish_store: PublishStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PUB-086 AC2: every lease the run committed is released; another run's lease is untouched."""
    # Another run already holds a fresh lease on "email" for the same image.
    other_run = await publish_store.acquire_lease("t1", IMAGE_SHA256, ["email"])
    assert set(other_run) == {"email"}

    calls: dict[str, int] = {}
    orchestrator = WorkflowOrchestrator(
        make_app_config(content={"archive": True}),
        _ArchiveTrackingStorage(images=["test.jpg"]),
        stub_ai_service(_CountingAnalyzer(delay=5.0)),
        [
            _ScriptedPublisher("telegram", [True], calls),
            _ScriptedPublisher("instagram", [True], calls),
            _ScriptedPublisher("email", [True], calls),
        ],
        tenant="t1",
        publish_store=publish_store,
    )
    gate = _LeaseCommitGate(monkeypatch)
    marks = _MarkRecorder(monkeypatch)

    task = asyncio.create_task(orchestrator.execute(select_filename="test.jpg"))
    # Parks after telegram's lease commit, before instagram is claimed.
    await _cancel_at_first_lease_commit(task, gate)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=15)

    by_platform = {r.platform: r for r in await _lease_rows(publish_store)}
    assert "telegram" in by_platform, "the first lease was committed before the cancel"
    wedged = sorted(p for p, r in by_platform.items() if p != "email" and r.status == "leased")
    assert wedged == [], f"leases this run committed were left wedged: {wedged}"

    email = by_platform["email"]
    assert email.status == "leased", "the other run's lease was touched"
    token = other_run["email"]
    stored = email.leased_at if email.leased_at.tzinfo else email.leased_at.replace(tzinfo=token.tzinfo)
    assert stored == token, "the other run's lease token was rewritten"
    this_run = {p for p in by_platform if p != "email"}
    _assert_releases_fenced_by_committed_tokens(marks, list(by_platform.values()), this_run)
    assert calls == {}


async def test_cancel_during_claim_still_raises_cancelled(
    publish_store: PublishStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PUB-086 AC3: a cancellation delivered during the claim is not swallowed."""
    orchestrator = WorkflowOrchestrator(
        make_app_config(content={"archive": True}),
        _ArchiveTrackingStorage(images=["test.jpg"]),
        stub_ai_service(_CountingAnalyzer(delay=5.0)),
        [_ScriptedPublisher("telegram", [True], {}), _ScriptedPublisher("instagram", [True], {})],
        tenant="t1",
        publish_store=publish_store,
    )
    gate = _LeaseCommitGate(monkeypatch)

    task = asyncio.create_task(orchestrator.execute(select_filename="test.jpg"))
    await _cancel_at_first_lease_commit(task, gate)
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(asyncio.shield(task), timeout=15)

    assert task.done()
    assert task.cancelled(), f"the cancelled run returned a normal result: {task.result()!r}"


async def test_second_cancel_during_claim_still_releases_committed_leases(
    publish_store: PublishStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PUB-086 AC6: a second cancel while the run waits for its shielded claim must not strand the lease."""
    calls: dict[str, int] = {}
    orchestrator = WorkflowOrchestrator(
        make_app_config(content={"archive": True}),
        _ArchiveTrackingStorage(images=["test.jpg"]),
        stub_ai_service(_CountingAnalyzer(delay=5.0)),
        [_ScriptedPublisher("telegram", [True], calls), _ScriptedPublisher("instagram", [True], calls)],
        tenant="t1",
        publish_store=publish_store,
    )
    gate = _LeaseCommitGate(monkeypatch)

    task = asyncio.create_task(orchestrator.execute(select_filename="test.jpg"))
    await asyncio.wait_for(gate.committed.wait(), timeout=10)
    task.cancel()
    # Let the first cancellation be delivered: the run is now waiting for its
    # shielded claim, which is still parked on the gate. Loop turns, not time.
    for _ in range(5):
        await asyncio.sleep(0)
    assert not task.done()
    task.cancel()  # the second cancel lands while the run waits for the claim
    for _ in range(5):
        await asyncio.sleep(0)
    gate.hold.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=15)

    rows = await _lease_rows(publish_store)
    assert "telegram" in {r.platform for r in rows}, "the first lease was committed before the cancel"
    wedged = sorted(r.platform for r in rows if r.status == "leased")
    assert wedged == [], f"leases the claim committed were left wedged: {wedged}"
    assert calls == {}


async def test_claim_timeout_after_a_commit_releases_it(
    publish_store: PublishStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PUB-086 AC7: the claim's own timeout expiring after a lease commit must release that lease."""
    from publisher_v2.config.runtime_settings import RuntimeSettings

    calls: dict[str, int] = {}
    orchestrator = WorkflowOrchestrator(
        make_app_config(content={"archive": True}),
        _ArchiveTrackingStorage(images=["test.jpg"]),
        stub_ai_service(_CountingAnalyzer()),
        [_ScriptedPublisher("telegram", [True], calls), _ScriptedPublisher("instagram", [True], calls)],
        tenant="t1",
        publish_store=publish_store,
        settings=RuntimeSettings(publish_claim_timeout_seconds=0.25),
    )
    # The gate holds after telegram's lease commit and is never released, so the
    # claim budget expires mid-claim. That budget is the only wait in this test.
    gate = _LeaseCommitGate(monkeypatch)
    marks = _MarkRecorder(monkeypatch)

    result = await asyncio.wait_for(orchestrator.execute(select_filename="test.jpg"), timeout=15)

    assert gate.committed.is_set(), "the lease row was committed before the claim timed out"
    assert result.success is False
    assert result.error == "publish_store_unavailable"
    rows = await _lease_rows(publish_store)
    assert "telegram" in {r.platform for r in rows}
    wedged = sorted(r.platform for r in rows if r.status == "leased")
    assert wedged == [], f"leases committed before the claim timeout were left wedged: {wedged}"
    _assert_releases_fenced_by_committed_tokens(marks, rows, {r.platform for r in rows})
    assert calls == {}


async def test_cancel_then_claim_timeout_releases_and_raises_cancelled(
    publish_store: PublishStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PUB-086 AC8: a cancel, then the claim timing out, still releases the lease and stays cancelled."""
    from publisher_v2.config.runtime_settings import RuntimeSettings

    calls: dict[str, int] = {}
    orchestrator = WorkflowOrchestrator(
        make_app_config(content={"archive": True}),
        _ArchiveTrackingStorage(images=["test.jpg"]),
        stub_ai_service(_CountingAnalyzer()),
        [_ScriptedPublisher("telegram", [True], calls), _ScriptedPublisher("instagram", [True], calls)],
        tenant="t1",
        publish_store=publish_store,
        settings=RuntimeSettings(publish_claim_timeout_seconds=1.0),
    )
    # The gate holds after telegram's lease commit and is not released (its own
    # hold is bounded at 10s), so the 1s claim budget expires while the run
    # is already waiting on its shielded claim after the cancel.
    gate = _LeaseCommitGate(monkeypatch)
    marks = _MarkRecorder(monkeypatch)

    task = asyncio.create_task(orchestrator.execute(select_filename="test.jpg"))
    await asyncio.wait_for(gate.committed.wait(), timeout=10)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=15)
    finally:
        gate.hold.set()

    rows = await _lease_rows(publish_store)
    assert "telegram" in {r.platform for r in rows}, "the lease row was committed before the cancel"
    wedged = sorted(r.platform for r in rows if r.status == "leased")
    assert wedged == [], f"leases committed before the cancel and claim timeout were left wedged: {wedged}"
    _assert_releases_fenced_by_committed_tokens(marks, rows, {r.platform for r in rows})
    assert calls == {}
