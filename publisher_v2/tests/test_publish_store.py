"""REL-2/REL-3 (#85): Postgres-backed publish records and lease.

Uses async SQLite (:memory:) via aiosqlite — same pattern as
test_caption_history_db.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from publisher_v2.db.models import Base
from publisher_v2.db.publish_store import PublishStore


@pytest.fixture
async def db_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


@pytest.fixture
async def store(db_session_factory):
    return PublishStore(db_session_factory)


class TestAcquireLease:
    async def test_lease_acquired_once(self, store: PublishStore) -> None:
        owned = await store.acquire_lease("t1", "hash1", ["telegram", "email"])
        assert owned == {"telegram", "email"}

    async def test_second_acquire_returns_empty(self, store: PublishStore) -> None:
        await store.acquire_lease("t1", "hash1", ["telegram", "email"])
        again = await store.acquire_lease("t1", "hash1", ["telegram", "email"])
        assert again == set()

    async def test_lease_is_tenant_scoped(self, store: PublishStore) -> None:
        await store.acquire_lease("t1", "hash1", ["telegram"])
        other_tenant = await store.acquire_lease("t2", "hash1", ["telegram"])
        assert other_tenant == {"telegram"}

    async def test_failed_platform_can_be_re_leased(self, store: PublishStore) -> None:
        await store.acquire_lease("t1", "hash1", ["instagram"])
        await store.mark("t1", "hash1", "instagram", "failed", error="RuntimeError: boom")
        again = await store.acquire_lease("t1", "hash1", ["instagram"])
        assert again == {"instagram"}

    async def test_unknown_platform_never_auto_retried(self, store: PublishStore) -> None:
        await store.acquire_lease("t1", "hash1", ["instagram"])
        await store.mark("t1", "hash1", "instagram", "unknown", error="publish timeout")
        again = await store.acquire_lease("t1", "hash1", ["instagram"])
        assert again == set()


class TestMarkAndPostedPlatforms:
    async def test_posted_platforms_after_marking(self, store: PublishStore) -> None:
        await store.acquire_lease("t1", "hash1", ["telegram", "instagram"])
        await store.mark("t1", "hash1", "telegram", "published", post_id="123")
        await store.mark("t1", "hash1", "instagram", "failed", error="RuntimeError: boom")

        posted = await store.posted_platforms("t1", "hash1")
        assert posted == {"telegram"}

    async def test_mark_stores_post_id_and_error(self, store: PublishStore, db_session_factory) -> None:
        from sqlalchemy import select

        from publisher_v2.db.models import PublishRecord

        await store.acquire_lease("t1", "hash1", ["telegram"])
        await store.mark("t1", "hash1", "telegram", "published", post_id="msg-9")

        async with db_session_factory() as session:
            row = (await session.execute(select(PublishRecord))).scalar_one()
        assert row.status == "published"
        assert row.post_id == "msg-9"
        assert row.finished_at is not None
