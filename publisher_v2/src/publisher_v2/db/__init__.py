"""Publisher V2 database layer.

Provides optional Postgres-backed persistence for caption history.
When DATABASE_URL is not set, all DB features gracefully degrade to no-ops.
"""

from __future__ import annotations

import logging
import os
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger("publisher_v2.db")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

_HEALTH_CHECK_TTL_SECONDS = 30.0
_health_cache: tuple[bool, float] | None = None


def _normalize_database_url(raw: str) -> str:
    """Normalise a database URL to the ``postgresql+asyncpg://`` scheme.

    Supports Heroku-style ``postgres://`` and plain ``postgresql://`` URLs.
    """
    if raw.startswith("postgres://"):
        return raw.replace("postgres://", "postgresql+asyncpg://", 1)
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    return raw


def is_db_available() -> bool:
    """Return True when a DATABASE_URL is configured."""
    return bool(os.environ.get("DATABASE_URL", "").strip())


def init_db() -> async_sessionmaker[AsyncSession] | None:
    """Create the async engine and session factory.

    Call once at process startup. Returns None when no DATABASE_URL is set.
    """
    global _engine, _session_factory  # noqa: PLW0603

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        logger.warning("DATABASE_URL not set — caption history DB disabled")
        return None

    url = _normalize_database_url(url)
    _engine = create_async_engine(
        url,
        echo=False,
        pool_size=3,
        max_overflow=5,
        pool_pre_ping=True,
    )
    _session_factory = async_sessionmaker(bind=_engine, expire_on_commit=False, class_=AsyncSession)
    logger.info("Caption history DB initialised (pool_size=3, max_overflow=5)")
    return _session_factory


def get_session_factory() -> async_sessionmaker[AsyncSession] | None:
    """Return the session factory, or None if DB was never initialised."""
    return _session_factory


def get_engine() -> AsyncEngine | None:
    """Return the engine, or None if DB was never initialised."""
    return _engine


async def dispose_engine() -> None:
    """Dispose the engine on shutdown. Safe to call even if engine is None."""
    global _engine, _session_factory  # noqa: PLW0603
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


async def check_connectivity() -> bool:
    """Lightweight connectivity check (``SELECT 1``).

    Results are cached for 30 seconds to avoid hitting the DB on every
    readiness probe.
    """
    global _health_cache  # noqa: PLW0603

    if _engine is None:
        return False

    now = time.monotonic()
    if _health_cache is not None:
        cached_ok, cached_at = _health_cache
        if now - cached_at < _HEALTH_CHECK_TTL_SECONDS:
            return cached_ok

    try:
        async with _engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        _health_cache = (True, now)
        return True
    except Exception:
        _health_cache = (False, now)
        return False
