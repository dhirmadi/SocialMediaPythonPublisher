"""Instagram session persistence (#94, standalone mode).

A ``SessionStore`` keeps instagrapi settings (device fingerprint, cookies,
uuids) across process restarts so each restart does not trigger a fresh
password login — the fastest way to a challenge. Two implementations:

- ``FileSessionStore``: JSON under the configured path (default: the
  ``session_file`` from config, falling back to ``$XDG_CACHE_HOME``).
- ``DbSessionStore``: one row per tenant in ``pv2_instagram_session``,
  encrypted at rest with a Fernet key derived from ``WEB_SESSION_SECRET``
  — this is what survives Heroku restarts.

``blocked_until`` implements the 24h challenge backoff.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from publisher_v2.utils.logging import log_json

logger = logging.getLogger("publisher_v2.instagram_session")

CHALLENGE_BACKOFF_HOURS = 24


class SessionStore(Protocol):
    async def load(self, tenant: str) -> dict[str, Any] | None: ...

    async def save(self, tenant: str, settings: dict[str, Any]) -> None: ...

    async def get_blocked_until(self, tenant: str) -> datetime | None: ...

    async def set_blocked_until(self, tenant: str, until: datetime | None) -> None: ...


def challenge_backoff_until() -> datetime:
    return datetime.now(UTC) + timedelta(hours=CHALLENGE_BACKOFF_HOURS)


class FileSessionStore:
    """JSON file session store (single-tenant standalone default)."""

    def __init__(self, path: str | None = None) -> None:
        if not path:
            base = os.environ.get("XDG_CACHE_HOME") or os.path.join(Path.home(), ".cache")
            path = os.path.join(base, "publisher_v2", "instagram_session.json")
        self._path = Path(path)

    def _blocked_path(self) -> Path:
        return self._path.with_suffix(self._path.suffix + ".blocked")

    async def load(self, tenant: str) -> dict[str, Any] | None:
        try:
            data = json.loads(self._path.read_text())
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    async def save(self, tenant: str, settings: dict[str, Any]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(settings))
            with contextlib.suppress(OSError):
                os.chmod(self._path, 0o600)
        except OSError:
            log_json(logger, logging.WARNING, "instagram_session_save_failed", exc_info=True)

    async def get_blocked_until(self, tenant: str) -> datetime | None:
        try:
            raw = self._blocked_path().read_text().strip()
            return datetime.fromisoformat(raw)
        except (OSError, ValueError):
            return None

    async def set_blocked_until(self, tenant: str, until: datetime | None) -> None:
        try:
            if until is None:
                self._blocked_path().unlink(missing_ok=True)
            else:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._blocked_path().write_text(until.isoformat())
        except OSError:
            log_json(logger, logging.WARNING, "instagram_backoff_save_failed", exc_info=True)


def _fernet_from_secret(secret: str):
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


class DbSessionStore:
    """Postgres-backed session store: one encrypted row per tenant."""

    def __init__(self, session_factory: Any, secret: str) -> None:
        self._session_factory = session_factory
        self._fernet = _fernet_from_secret(secret)

    async def _get_row(self, session: Any, tenant: str):
        from sqlalchemy import select

        from publisher_v2.db.models import InstagramSession

        return (
            await session.execute(select(InstagramSession).where(InstagramSession.tenant == tenant))
        ).scalar_one_or_none()

    async def load(self, tenant: str) -> dict[str, Any] | None:
        try:
            async with self._session_factory() as session:
                row = await self._get_row(session, tenant)
            if row is None or not row.session_blob:
                return None
            decrypted = self._fernet.decrypt(row.session_blob.encode("ascii"))
            data = json.loads(decrypted)
            return data if isinstance(data, dict) else None
        except Exception:
            log_json(logger, logging.WARNING, "instagram_session_load_failed", exc_info=True)
            return None

    async def save(self, tenant: str, settings: dict[str, Any]) -> None:
        try:
            blob = self._fernet.encrypt(json.dumps(settings).encode("utf-8")).decode("ascii")
            async with self._session_factory() as session:
                row = await self._get_row(session, tenant)
                if row is None:
                    from publisher_v2.db.models import InstagramSession

                    row = InstagramSession(tenant=tenant)
                    session.add(row)
                row.session_blob = blob
                row.updated_at = datetime.now(UTC)
                await session.commit()
        except Exception:
            log_json(logger, logging.WARNING, "instagram_session_save_failed", exc_info=True)

    async def get_blocked_until(self, tenant: str) -> datetime | None:
        try:
            async with self._session_factory() as session:
                row = await self._get_row(session, tenant)
            return row.blocked_until if row is not None else None
        except Exception:
            return None

    async def set_blocked_until(self, tenant: str, until: datetime | None) -> None:
        try:
            async with self._session_factory() as session:
                row = await self._get_row(session, tenant)
                if row is None:
                    from publisher_v2.db.models import InstagramSession

                    row = InstagramSession(tenant=tenant, session_blob="")
                    session.add(row)
                row.blocked_until = until
                row.updated_at = datetime.now(UTC)
                await session.commit()
        except Exception:
            log_json(logger, logging.WARNING, "instagram_backoff_save_failed", exc_info=True)


def build_session_store(session_file: str | None = None) -> SessionStore:
    """Pick the store: Postgres when available (survives restarts), else file."""
    from publisher_v2.db import get_session_factory

    secret = (os.environ.get("WEB_SESSION_SECRET") or os.environ.get("SECRET_KEY") or "").strip()
    factory = get_session_factory()
    if factory is not None and secret:
        return DbSessionStore(factory, secret)
    return FileSessionStore(session_file)
