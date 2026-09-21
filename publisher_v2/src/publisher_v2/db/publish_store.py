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
        # Unreachable while the column is non-nullable, and deliberately NOT a
        # reclaim signal if that ever changes: the SQL guard below tests
        # ``leased_at < cutoff``, which is NULL — never true — for a NULL
        # timestamp, so answering True here would report an ownership the
        # UPDATE could not take.
        return False
    if leased_at.tzinfo is None:
        leased_at = leased_at.replace(tzinfo=UTC)
    return (datetime.now(UTC) - leased_at).total_seconds() > ttl_seconds


class PublishStore:
    """Async repository for the publish lease and per-platform publish state."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], lease_ttl_seconds: float | None = None
    ) -> None:
        """Bind the store to a session factory and fix its lease TTL.

        Args:
            session_factory: Async SQLAlchemy session factory for the caption history DB.
            lease_ttl_seconds: How long a ``leased`` row stays owned before another run may
                reclaim it. ``None`` defers to the runtime settings, read at acquire time;
                pass it explicitly so the DB layer does not re-read the environment on every
                ``acquire_lease`` (#139/#162).
        """
        self._session_factory = session_factory
        # #139/#162: the TTL is a caller-supplied setting, not something the DB
        # layer reads from the environment on every acquire_lease.
        self._lease_ttl_seconds = lease_ttl_seconds

    async def acquire_lease(self, tenant: str, content_hash: str, platforms: list[str]) -> dict[str, datetime]:
        """Claim platforms for this run. Returns ``{platform: lease token}`` for the ones it owns.

        The token is the exact ``leased_at`` this run stamped. Passing it back to
        ``mark`` fences the write: a run whose lease was reclaimed after its TTL
        lapsed can no longer overwrite the status of the run that took it over.

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
        ttl_seconds = (
            self._lease_ttl_seconds
            if self._lease_ttl_seconds is not None
            else load_runtime_settings().publish_lease_ttl_seconds
        )
        owned: dict[str, datetime] = {}
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
                    # Stamped here rather than by the column's server default, so
                    # the value handed back as the token is exactly the one in
                    # the row (the default has second precision).
                    token = datetime.now(UTC)
                    session.add(
                        PublishRecord(
                            tenant=tenant,
                            content_hash=content_hash,
                            platform=platform,
                            status="leased",
                            leased_at=token,
                        )
                    )
                    try:
                        await session.commit()
                        owned[platform] = token
                    except IntegrityError:
                        # Lost the race to a concurrent run — it owns the lease.
                        await session.rollback()
                elif existing.status == "failed":
                    token = datetime.now(UTC)
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
                            leased_at=token,
                            error=None,
                            finished_at=None,
                        )
                        .execution_options(synchronize_session=False)
                    )
                    await session.commit()
                    if getattr(result, "rowcount", 0) == 1:
                        # Lost the race to a concurrent re-lease attempt otherwise.
                        owned[platform] = token
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
                    token = datetime.now(UTC)
                    result = await session.execute(
                        sa_update(PublishRecord)
                        .where(
                            PublishRecord.tenant == tenant,
                            PublishRecord.content_hash == content_hash,
                            PublishRecord.platform == platform,
                            PublishRecord.status == "leased",
                            PublishRecord.leased_at < cutoff,
                        )
                        .values(status="leased", leased_at=token, error=None, finished_at=None)
                        .execution_options(synchronize_session=False)
                    )
                    await session.commit()
                    if getattr(result, "rowcount", 0) == 1:
                        owned[platform] = token
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
        lease_token: datetime | None = None,
    ) -> bool:
        """Record the outcome for one platform. Returns whether the write landed.

        With ``lease_token`` the write is fenced: it only lands while the row
        still carries the ``leased_at`` this run stamped. Without the fence, a
        run whose lease had already been reclaimed past the TTL could mark the
        row ``failed`` — making it re-leasable — while the run that took it over
        was still publishing, so a third run could post the same image again.
        """
        async with self._session_factory() as session:
            if lease_token is not None:
                result = await session.execute(
                    sa_update(PublishRecord)
                    .where(
                        PublishRecord.tenant == tenant,
                        PublishRecord.content_hash == content_hash,
                        PublishRecord.platform == platform,
                        PublishRecord.leased_at == lease_token,
                    )
                    .values(status=status, post_id=post_id, error=error, finished_at=datetime.now(UTC))
                    .execution_options(synchronize_session=False)
                )
                await session.commit()
                if getattr(result, "rowcount", 0) == 1:
                    return True
                log_json(
                    logger,
                    logging.WARNING,
                    "publish_mark_lease_lost",
                    tenant=tenant,
                    platform=platform,
                    status=status,
                )
                return False
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
            return True

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
