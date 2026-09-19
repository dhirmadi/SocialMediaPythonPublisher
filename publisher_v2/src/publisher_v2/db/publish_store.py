"""Repository for per-platform publish records and the publish lease (#85).

Keys: (tenant, content_hash, platform), unique. Status lifecycle:
leased → published | failed | unknown. ``failed`` rows are re-leasable so a
partial publish retries only the failed platform; ``unknown`` rows (publish
timeout — the upload may have completed upstream) are never retried
automatically and need operator attention.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from publisher_v2.db.models import PublishRecord

logger = logging.getLogger("publisher_v2.db.publish_store")


class PublishStore:
    """Async repository for the publish lease and per-platform publish state."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def acquire_lease(self, tenant: str, content_hash: str, platforms: list[str]) -> set[str]:
        """Claim platforms for this run. Returns the set this run owns.

        - No row → insert a ``leased`` row and own the platform.
        - ``failed`` row → re-lease (retry allowed) and own it.
        - ``leased`` / ``published`` / ``unknown`` row → skip.

        A concurrent insert losing the unique-constraint race simply does not
        own that platform.
        """
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
                    existing.status = "leased"
                    existing.leased_at = datetime.now(UTC)
                    existing.error = None
                    existing.finished_at = None
                    await session.commit()
                    owned.add(platform)
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
