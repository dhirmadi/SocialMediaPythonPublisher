"""Repository for per-platform publish records and the publish lease (#85).

Keys: (tenant, content_hash, platform), unique. Status lifecycle:
leased → published | failed | unknown. ``failed`` rows are re-leasable so a
partial publish retries only the failed platform; ``unknown`` rows (publish
timeout — the upload may have completed upstream) are never retried
automatically and need operator attention.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from publisher_v2.config.runtime_settings import load_runtime_settings
from publisher_v2.db.models import PublishRecord
from publisher_v2.utils.logging import log_json

logger = logging.getLogger("publisher_v2.db.publish_store")


def _is_stale(leased_at: datetime | None, ttl_seconds: float) -> bool:
    """True when a ``leased`` row is older than the lease TTL (#139).

    Naive timestamps (SQLite) are read as UTC, matching how they are written.
    """
    if leased_at is None:
        return True
    if leased_at.tzinfo is None:
        leased_at = leased_at.replace(tzinfo=UTC)
    return (datetime.now(UTC) - leased_at).total_seconds() > ttl_seconds


class PublishStore:
    """Async repository for the publish lease and per-platform publish state."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def acquire_lease(self, tenant: str, content_hash: str, platforms: list[str]) -> set[str]:
        """Claim platforms for this run. Returns the set this run owns.

        - No row → insert a ``leased`` row and own the platform.
        - ``failed`` row → re-lease (retry allowed) and own it.
        - ``leased`` / ``published`` / ``unknown`` row → skip.

        Both branches are race-safe against concurrent callers racing on the
        *same* (tenant, content_hash, platform):

        - The insert branch relies on the unique constraint — a concurrent
          insert that loses the race gets an ``IntegrityError`` and simply
          does not own that platform.
        - The re-lease branch uses a single conditional
          ``UPDATE ... WHERE status = 'failed'`` rather than a read-then-write
          of the ORM object, so only the run whose UPDATE actually flips the
          row (``rowcount == 1``) owns it. A second concurrent re-lease
          attempt re-evaluates the WHERE clause against the now-committed row
          and affects zero rows, instead of a stale in-memory read letting
          both callers believe they won the lease.
        """
        ttl_seconds = load_runtime_settings().publish_lease_ttl_seconds
        owned: set[str] = set()
        for platform in platforms:
            async with self._session_factory() as session:
                existing = (
                    await session.execute(
                        select(PublishRecord).where(
                            PublishRecord.tenant == tenant,
                            PublishRecord.content_hash == content_hash,
                            PublishRecord.platform == platform,
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    session.add(
                        PublishRecord(tenant=tenant, content_hash=content_hash, platform=platform, status="leased")
                    )
                    try:
                        await session.commit()
                        owned.add(platform)
                    except IntegrityError:
                        # Lost the race to a concurrent run — it owns the lease.
                        await session.rollback()
                elif existing.status == "failed":
                    result = await session.execute(
                        sa_update(PublishRecord)
                        .where(
                            PublishRecord.tenant == tenant,
                            PublishRecord.content_hash == content_hash,
                            PublishRecord.platform == platform,
                            PublishRecord.status == "failed",
                        )
                        .values(
                            status="leased",
                            leased_at=datetime.now(UTC),
                            error=None,
                            finished_at=None,
                        )
                        .execution_options(synchronize_session=False)
                    )
                    await session.commit()
                    if getattr(result, "rowcount", 0) == 1:
                        # Lost the race to a concurrent re-lease attempt otherwise.
                        owned.add(platform)
                elif existing.status == "leased" and _is_stale(existing.leased_at, ttl_seconds):
                    # #139: the run holding this lease crashed between the lease
                    # and the mark. Reclaim with a single conditional UPDATE that
                    # re-tests staleness in SQL (``leased_at < cutoff``): the
                    # winner stamps a fresh ``leased_at``, so a concurrent
                    # reclaim re-evaluates the WHERE against the committed row,
                    # matches nothing and does not also believe it won. The
                    # cutoff is compared, never the exact ``leased_at`` we read —
                    # rows stamped by the column's server default have
                    # second-precision timestamps that an equality test misses.
                    cutoff = datetime.now(UTC) - timedelta(seconds=ttl_seconds)
                    result = await session.execute(
                        sa_update(PublishRecord)
                        .where(
                            PublishRecord.tenant == tenant,
                            PublishRecord.content_hash == content_hash,
                            PublishRecord.platform == platform,
                            PublishRecord.status == "leased",
                            PublishRecord.leased_at < cutoff,
                        )
                        .values(status="leased", leased_at=datetime.now(UTC), error=None, finished_at=None)
                        .execution_options(synchronize_session=False)
                    )
                    await session.commit()
                    if getattr(result, "rowcount", 0) == 1:
                        owned.add(platform)
                        log_json(
                            logger,
                            logging.WARNING,
                            "publish_lease_reclaimed",
                            tenant=tenant,
                            platform=platform,
                            ttl_seconds=ttl_seconds,
                        )
        return owned

    async def mark(
        self,
        tenant: str,
        content_hash: str,
        platform: str,
        status: str,
        post_id: str | None = None,
        error: str | None = None,
    ) -> None:
        """Record the outcome for one platform."""
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(PublishRecord).where(
                        PublishRecord.tenant == tenant,
                        PublishRecord.content_hash == content_hash,
                        PublishRecord.platform == platform,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = PublishRecord(tenant=tenant, content_hash=content_hash, platform=platform)
                session.add(row)
            row.status = status
            row.post_id = post_id
            row.error = error
            row.finished_at = datetime.now(UTC)
            await session.commit()

    async def posted_platforms(self, tenant: str, content_hash: str) -> set[str]:
        """Platforms already ``published`` for this tenant + content hash."""
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(PublishRecord.platform).where(
                        PublishRecord.tenant == tenant,
                        PublishRecord.content_hash == content_hash,
                        PublishRecord.status == "published",
                    )
                )
            ).all()
        return {platform for (platform,) in rows}
