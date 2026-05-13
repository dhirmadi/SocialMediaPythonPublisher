"""Tests for DB-backed caption history (GH #72).

Uses async SQLite (:memory:) via aiosqlite — no Postgres needed in CI.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from publisher_v2.db.caption_store import CaptionStore
from publisher_v2.db.models import Base, CaptionHistory

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session_factory():
    """Create an in-memory SQLite async engine + session factory with tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    yield factory

    await engine.dispose()


@pytest.fixture
async def store(db_session_factory):
    """CaptionStore backed by in-memory SQLite."""
    return CaptionStore(db_session_factory)


# ---------------------------------------------------------------------------
# CaptionStore: save + fetch round-trip
# ---------------------------------------------------------------------------


class TestCaptionStoreSaveFetch:
    async def test_save_batch_and_fetch_by_platform(self, store: CaptionStore) -> None:
        saved = await store.save_captions_batch(
            tenant="t1",
            captions_by_platform={"email": "Short caption", "telegram": "Longer telegram caption here"},
        )
        assert saved == 2

        by_platform = await store.fetch_recent_by_platform("t1", platforms=["email", "telegram"])
        assert "email" in by_platform
        assert "telegram" in by_platform
        assert by_platform["email"] == ["Short caption"]
        assert by_platform["telegram"] == ["Longer telegram caption here"]

    async def test_fetch_by_platform_returns_empty_for_unknown(self, store: CaptionStore) -> None:
        result = await store.fetch_recent_by_platform("t1", platforms=["instagram"])
        assert result == {}

    async def test_fetch_by_platform_ordering_most_recent_first(self, store: CaptionStore) -> None:
        for i in range(5):
            await store.save_captions_batch(tenant="t1", captions_by_platform={"email": f"Caption {i}"})
        by_platform = await store.fetch_recent_by_platform("t1", platforms=["email"], limit=5)
        assert by_platform["email"] == ["Caption 4", "Caption 3", "Caption 2", "Caption 1", "Caption 0"]

    async def test_fetch_by_platform_multi_platform_ordering(self, store: CaptionStore) -> None:
        for i in range(3):
            await store.save_captions_batch(
                tenant="t1", captions_by_platform={"email": f"Email {i}", "telegram": f"Telegram {i}"}
            )

        by_platform = await store.fetch_recent_by_platform("t1", platforms=["email"])
        assert by_platform["email"] == ["Email 2", "Email 1", "Email 0"]

    async def test_fetch_by_platform_respects_limit(self, store: CaptionStore) -> None:
        for i in range(10):
            await store.save_captions_batch(tenant="t1", captions_by_platform={"email": f"Cap {i}"})
        by_platform = await store.fetch_recent_by_platform("t1", platforms=["email"], limit=3)
        assert len(by_platform["email"]) == 3
        assert by_platform["email"][0] == "Cap 9"


class TestCaptionStoreTenantIsolation:
    async def test_tenants_are_isolated(self, store: CaptionStore) -> None:
        await store.save_captions_batch(tenant="t1", captions_by_platform={"email": "Tenant 1 caption"})
        await store.save_captions_batch(tenant="t2", captions_by_platform={"email": "Tenant 2 caption"})

        t1 = await store.fetch_recent_by_platform("t1", platforms=["email"])
        t2 = await store.fetch_recent_by_platform("t2", platforms=["email"])
        assert t1["email"] == ["Tenant 1 caption"]
        assert t2["email"] == ["Tenant 2 caption"]

    async def test_fetch_by_platform_tenant_isolation(self, store: CaptionStore) -> None:
        await store.save_captions_batch(tenant="t1", captions_by_platform={"email": "T1 email"})
        await store.save_captions_batch(tenant="t2", captions_by_platform={"email": "T2 email"})

        by_platform = await store.fetch_recent_by_platform("t1", platforms=["email"])
        assert by_platform["email"] == ["T1 email"]


class TestCaptionStoreMetadata:
    async def test_truncation_metadata_saved(self, store: CaptionStore) -> None:
        await store.save_captions_batch(
            tenant="t1",
            captions_by_platform={"email": "Truncated caption"},
            truncation_info={"email": (True, 320)},
        )
        async with store._session_factory() as session:
            from sqlalchemy import select

            rows = (await session.execute(select(CaptionHistory))).scalars().all()
            assert len(rows) == 1
            assert rows[0].was_truncated is True
            assert rows[0].original_length == 320

    async def test_caption_source_default(self, store: CaptionStore) -> None:
        await store.save_captions_batch(tenant="t1", captions_by_platform={"email": "Test"})
        async with store._session_factory() as session:
            from sqlalchemy import select

            row = (await session.execute(select(CaptionHistory))).scalar_one()
            assert row.caption_source == "ai_generated"

    async def test_caption_source_override(self, store: CaptionStore) -> None:
        await store.save_captions_batch(
            tenant="t1", captions_by_platform={"email": "Manual"}, caption_source="manual_override"
        )
        async with store._session_factory() as session:
            from sqlalchemy import select

            row = (await session.execute(select(CaptionHistory))).scalar_one()
            assert row.caption_source == "manual_override"

    async def test_model_version_saved(self, store: CaptionStore) -> None:
        await store.save_captions_batch(
            tenant="t1", captions_by_platform={"email": "Test"}, model_version="gpt-4o-2025-05"
        )
        async with store._session_factory() as session:
            from sqlalchemy import select

            row = (await session.execute(select(CaptionHistory))).scalar_one()
            assert row.model_version == "gpt-4o-2025-05"

    async def test_empty_batch_returns_zero(self, store: CaptionStore) -> None:
        saved = await store.save_captions_batch(tenant="t1", captions_by_platform={})
        assert saved == 0


class TestCaptionStoreRetention:
    async def test_prune_deletes_old_records(self, store: CaptionStore, db_session_factory) -> None:
        async with db_session_factory() as session:
            old_ts = datetime.now(UTC) - timedelta(days=120)
            for i in range(5):
                session.add(
                    CaptionHistory(
                        tenant="t1",
                        platform="email",
                        caption_text=f"Old {i}",
                        created_at=old_ts + timedelta(minutes=i),
                    )
                )
            new_ts = datetime.now(UTC) - timedelta(days=10)
            for i in range(3):
                session.add(
                    CaptionHistory(
                        tenant="t1",
                        platform="email",
                        caption_text=f"New {i}",
                        created_at=new_ts + timedelta(minutes=i),
                    )
                )
            await session.commit()

        await store.prune_expired("t1", retention_days=90, min_keep_per_platform=0)
        remaining = await store.fetch_recent_by_platform("t1", platforms=["email"], limit=100)
        assert len(remaining["email"]) == 3
        assert all(r.startswith("New") for r in remaining["email"])

    async def test_prune_respects_safety_floor(self, store: CaptionStore, db_session_factory) -> None:
        """Even if all records are old, keep at least min_keep_per_platform."""
        async with db_session_factory() as session:
            old_ts = datetime.now(UTC) - timedelta(days=200)
            for i in range(10):
                session.add(
                    CaptionHistory(
                        tenant="t1",
                        platform="email",
                        caption_text=f"Ancient {i}",
                        created_at=old_ts + timedelta(minutes=i),
                    )
                )
            await session.commit()

        await store.prune_expired("t1", retention_days=90, min_keep_per_platform=20)
        remaining = await store.fetch_recent_by_platform("t1", platforms=["email"], limit=100)
        assert len(remaining["email"]) == 10

    async def test_prune_zero_retention_is_noop(self, store: CaptionStore) -> None:
        await store.save_captions_batch(tenant="t1", captions_by_platform={"email": "Test"})
        deleted = await store.prune_expired("t1", retention_days=0)
        assert deleted == 0


# ---------------------------------------------------------------------------
# Per-platform history block in prompt
# ---------------------------------------------------------------------------


class TestPerPlatformHistoryBlock:
    def test_build_platform_block_with_history(self) -> None:
        from publisher_v2.core.models import CaptionSpec
        from publisher_v2.services.ai import build_platform_block

        spec = CaptionSpec(platform="email", style="intimate question", max_length=240, hashtags="")
        block = build_platform_block(1, "email", spec, platform_history=["Cap A", "Cap B"])
        assert "Your recent email captions" in block
        assert '"Cap A"' in block
        assert '"Cap B"' in block
        assert "DIFFERENT openings" in block

    def test_build_platform_block_without_history(self) -> None:
        from publisher_v2.core.models import CaptionSpec
        from publisher_v2.services.ai import build_platform_block

        spec = CaptionSpec(platform="email", style="intimate question", max_length=240, hashtags="")
        block = build_platform_block(1, "email", spec, platform_history=None)
        assert "recent" not in block.lower() or "recent email captions" not in block

    def test_build_platform_block_empty_history(self) -> None:
        from publisher_v2.core.models import CaptionSpec
        from publisher_v2.services.ai import build_platform_block

        spec = CaptionSpec(platform="email", style="intimate question", max_length=240, hashtags="")
        block = build_platform_block(1, "email", spec, platform_history=[])
        assert "recent email captions" not in block


class TestMultiPromptPerPlatformHistory:
    def test_dict_history_injected_per_platform(self) -> None:
        from publisher_v2.core.models import CaptionSpec, ImageAnalysis
        from publisher_v2.services.ai import CaptionGeneratorOpenAI

        analysis = ImageAnalysis(description="test", mood="moody", tags=["art"], nsfw=False)
        specs = {
            "email": CaptionSpec(platform="email", style="intimate", max_length=240, hashtags=""),
            "telegram": CaptionSpec(platform="telegram", style="conversational", max_length=4096, hashtags=""),
        }
        history = {"email": ["Email cap 1"], "telegram": ["Telegram cap 1"]}

        prompt, _ = CaptionGeneratorOpenAI._build_multi_prompt("Write captions:", analysis, specs, history)

        assert "recent email captions" in prompt
        assert '"Email cap 1"' in prompt
        assert "recent telegram captions" in prompt
        assert '"Telegram cap 1"' in prompt

    def test_flat_list_history_still_works(self) -> None:
        from publisher_v2.core.models import CaptionSpec, ImageAnalysis
        from publisher_v2.services.ai import CaptionGeneratorOpenAI

        analysis = ImageAnalysis(description="test", mood="moody", tags=["art"], nsfw=False)
        specs = {"email": CaptionSpec(platform="email", style="intimate", max_length=240, hashtags="")}
        history = ["Cap 1", "Cap 2"]

        prompt, _ = CaptionGeneratorOpenAI._build_multi_prompt("Write captions:", analysis, specs, history)

        assert "DO NOT repeat phrasing" in prompt
        assert '"Cap 1"' in prompt

    def test_none_history_produces_no_block(self) -> None:
        from publisher_v2.core.models import CaptionSpec, ImageAnalysis
        from publisher_v2.services.ai import CaptionGeneratorOpenAI

        analysis = ImageAnalysis(description="test", mood="moody", tags=["art"], nsfw=False)
        specs = {"email": CaptionSpec(platform="email", style="intimate", max_length=240, hashtags="")}

        prompt, _ = CaptionGeneratorOpenAI._build_multi_prompt("Write captions:", analysis, specs, None)

        assert "recent" not in prompt.lower() or "recent email captions" not in prompt


# ---------------------------------------------------------------------------
# Workflow integration (mocked)
# ---------------------------------------------------------------------------


class TestWorkflowCaptionHistory:
    async def test_workflow_saves_captions_on_success(self) -> None:
        """After successful publish, workflow calls caption_store.save_captions_batch."""
        from publisher_v2.core.workflow import WorkflowOrchestrator

        mock_store = AsyncMock(spec=CaptionStore)
        mock_store.fetch_recent_by_platform.return_value = {}
        mock_store.save_captions_batch.return_value = 2

        config = MagicMock()
        config.features.analyze_caption_enabled = False
        config.features.publish_enabled = True
        config.features.voice_matching_enabled = False
        config.content.archive = False
        config.content.debug = False
        config.storage_paths.image_folder = "/images"
        config.storage_paths.archive_folder = "/archive"

        storage = AsyncMock()
        storage.list_images.return_value = ["test.jpg"]
        storage.download_image.return_value = b"fake"
        storage.supports_content_hashing.return_value = False
        storage.get_temp_link.return_value = "http://example.com/test.jpg"

        ai_service = MagicMock()
        publisher = MagicMock()
        publisher.is_enabled.return_value = True
        publisher.platform_name = "email"
        publish_result = MagicMock(success=True, platform="email")
        publisher.publish = AsyncMock(return_value=publish_result)

        orchestrator = WorkflowOrchestrator(
            config, storage, ai_service, [publisher], tenant="test_tenant", caption_store=mock_store
        )

        assert orchestrator._caption_store is mock_store
        assert orchestrator._tenant == "test_tenant"

    async def test_workflow_works_without_caption_store(self) -> None:
        """Workflow doesn't crash when caption_store is None (graceful degradation)."""
        from publisher_v2.core.workflow import WorkflowOrchestrator

        config = MagicMock()
        storage = AsyncMock()
        storage.supports_content_hashing.return_value = False
        ai_service = MagicMock()

        orchestrator = WorkflowOrchestrator(config, storage, ai_service, [], caption_store=None)
        assert orchestrator._caption_store is None
        assert orchestrator._tenant == "default"


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    def test_is_db_available_without_env(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            from publisher_v2.db import is_db_available

            assert is_db_available() is False

    def test_is_db_available_with_env(self) -> None:
        with patch.dict("os.environ", {"DATABASE_URL": "postgres://x:y@host:5432/db"}):
            from publisher_v2.db import is_db_available

            assert is_db_available() is True

    def test_init_db_returns_none_without_url(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            from publisher_v2.db import init_db

            result = init_db()
            assert result is None


# ---------------------------------------------------------------------------
# DB module helpers
# ---------------------------------------------------------------------------


class TestDBHelpers:
    def test_normalize_heroku_url(self) -> None:
        from publisher_v2.db import _normalize_database_url

        assert _normalize_database_url("postgres://u:p@h:5432/db").startswith("postgresql+asyncpg://")
        assert _normalize_database_url("postgresql://u:p@h:5432/db").startswith("postgresql+asyncpg://")
        assert _normalize_database_url("postgresql+asyncpg://u:p@h:5432/db") == "postgresql+asyncpg://u:p@h:5432/db"
