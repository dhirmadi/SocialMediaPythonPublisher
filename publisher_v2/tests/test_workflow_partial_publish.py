"""REL-2/REL-3 (#85): partial publish never archives, never double-posts.

Telegram OK + Instagram failed must leave the image unarchived with a failed
Instagram record; the next run publishes only to Instagram.
"""

from __future__ import annotations

import asyncio
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
    publish_store: PublishStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A publisher that hangs past the deadline is marked ``unknown``, not ``failed``.

    ``unknown`` rows are never auto-retried (the upload may have completed
    upstream) and the run must not archive, since not every platform reached
    ``published``.
    """
    import publisher_v2.core.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "_publish_timeout_seconds", lambda: 0.05)
    monkeypatch.setattr(workflow_module, "_publish_timeout_for", lambda platform, default: 0.05)

    calls: dict[str, int] = {}
    publishers: list[Publisher] = [
        _ScriptedPublisher("telegram", [True], calls),
        _HangingPublisher("instagram", calls),
    ]
    storage = _ArchiveTrackingStorage(images=["test.jpg"])
    orchestrator = WorkflowOrchestrator(
        _config(), storage, _DummyAI(), publishers, tenant="t1", publish_store=publish_store
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
