"""Repository for caption history persistence and retrieval."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from publisher_v2.db.models import CaptionHistory

logger = logging.getLogger("publisher_v2.db.caption_store")

_DEFAULT_RETENTION_DAYS = 90
_DEFAULT_MIN_KEEP = 20


class CaptionStore:
    """Async repository for per-tenant, per-platform caption history."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @property
    def _retention_days(self) -> int:
        try:
            return int(os.environ.get("PV2_CAPTION_HISTORY_RETENTION_DAYS", _DEFAULT_RETENTION_DAYS))
        except (ValueError, TypeError):
            return _DEFAULT_RETENTION_DAYS

    async def save_captions_batch(
        self,
        *,
        tenant: str,
        captions_by_platform: dict[str, str],
        image_filename: str | None = None,
        image_sha256: str | None = None,
        correlation_id: str | None = None,
        model_version: str | None = None,
        caption_source: str = "ai_generated",
        truncation_info: dict[str, tuple[bool, int | None]] | None = None,
    ) -> int:
        """Insert one row per platform after a multi-platform publish.

        ``truncation_info`` maps platform -> (was_truncated, original_length).
        Returns the number of rows inserted.

        Also triggers retention pruning after the insert.
        """
        if not captions_by_platform:
            return 0

        rows_inserted = 0
        async with self._session_factory() as session:
            for platform, caption_text in captions_by_platform.items():
                was_truncated = False
                original_length: int | None = None
                if truncation_info and platform in truncation_info:
                    was_truncated, original_length = truncation_info[platform]

                row = CaptionHistory(
                    tenant=tenant,
                    platform=platform,
                    caption_text=caption_text,
                    image_filename=image_filename,
                    image_sha256=image_sha256,
                    correlation_id=correlation_id,
                    model_version=model_version,
                    caption_source=caption_source,
                    was_truncated=was_truncated,
                    original_length=original_length,
                )
                session.add(row)
                rows_inserted += 1
            await session.commit()

        try:
            await self.prune_expired(tenant)
        except Exception:
            logger.debug("caption_history_prune_failed", exc_info=True)

        return rows_inserted

    async def fetch_recent_by_platform(
        self,
        tenant: str,
        platforms: list[str] | None = None,
        limit: int = 8,
    ) -> dict[str, list[str]]:
        """Fetch recent captions grouped by platform.

        Returns a dict mapping platform name to a list of caption strings,
        ordered most-recent-first. Each platform gets up to ``limit`` captions.

        Uses a single query with a window function to avoid N+1 round-trips.
        """
        from sqlalchemy import func as sa_func

        async with self._session_factory() as session:
            # Row-number window to pick the N most recent per platform
            row_num = (
                sa_func.row_number()
                .over(
                    partition_by=CaptionHistory.platform,
                    order_by=[CaptionHistory.created_at.desc(), CaptionHistory.id.desc()],
                )
                .label("rn")
            )

            inner = select(CaptionHistory.platform, CaptionHistory.caption_text, row_num).where(
                CaptionHistory.tenant == tenant
            )
            if platforms:
                inner = inner.where(CaptionHistory.platform.in_(platforms))
            inner = inner.subquery()

            stmt = (
                select(inner.c.platform, inner.c.caption_text)
                .where(inner.c.rn <= limit)
                .order_by(inner.c.platform, inner.c.rn)
            )
            rows = await session.execute(stmt)

            result: dict[str, list[str]] = {}
            for platform, caption_text in rows:
                result.setdefault(platform, []).append(caption_text)

        return result

    async def prune_expired(
        self,
        tenant: str,
        retention_days: int | None = None,
        min_keep_per_platform: int = _DEFAULT_MIN_KEEP,
    ) -> int:
        """Delete records older than the retention window.

        Always keeps at least ``min_keep_per_platform`` rows per tenant+platform
        regardless of age.
        Returns the number of deleted rows.
        """
        days = retention_days if retention_days is not None else self._retention_days
        if days <= 0:
            return 0

        cutoff = datetime.now(UTC) - timedelta(days=days)

        async with self._session_factory() as session:
            if min_keep_per_platform > 0:
                # Find IDs of the N newest rows per tenant (across all platforms)
                # to protect them from deletion regardless of age.
                keep_ids_sub = (
                    select(CaptionHistory.id)
                    .where(CaptionHistory.tenant == tenant)
                    .order_by(CaptionHistory.created_at.desc(), CaptionHistory.id.desc())
                    .limit(min_keep_per_platform)
                ).scalar_subquery()

                stmt = (
                    delete(CaptionHistory)
                    .where(CaptionHistory.tenant == tenant)
                    .where(CaptionHistory.created_at < cutoff)
                    .where(CaptionHistory.id.not_in(keep_ids_sub))
                )
            else:
                stmt = (
                    delete(CaptionHistory)
                    .where(CaptionHistory.tenant == tenant)
                    .where(CaptionHistory.created_at < cutoff)
                )

            result = await session.execute(stmt)
            await session.commit()
            deleted: int = getattr(result, "rowcount", 0) or 0
            if deleted:
                logger.info("caption_history_pruned tenant=%s deleted=%d retention_days=%d", tenant, deleted, days)
            return deleted
