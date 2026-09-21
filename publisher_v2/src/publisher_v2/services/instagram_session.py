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

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from publisher_v2.utils.logging import log_json

logger = logging.getLogger("publisher_v2.instagram_session")

# Instagram refused the login itself — a challenge, 2FA, or bad credentials.
# Retrying soon just re-triggers it, so sit out a day.
CHALLENGE_BACKOFF_HOURS = 24

# The login never reached a verdict: a network error, throttling, or the
# publish timeout cancelling the task. A failed password login must still not
# repeat on every publish, but a day is a large blast radius for a scheduled
# publisher when the cause may already be gone.
TRANSIENT_BACKOFF_HOURS = 1


class SessionStore(Protocol):
    """Per-tenant store for instagrapi settings and the challenge backoff.

    Implementations are expected to swallow their own storage errors and
    degrade to "no session" rather than raising into a publish: a missing
    session only costs a password login, while an exception would abort the
    publish entirely.
    """

    async def load(self, tenant: str) -> dict[str, Any] | None:
        """Return the stored instagrapi settings, or None when there are none."""
        ...

    async def save(self, tenant: str, settings: dict[str, Any]) -> None:
        """Persist the instagrapi settings for ``tenant``, replacing any earlier ones."""
        ...

    async def get_blocked_until(self, tenant: str) -> datetime | None:
        """Return the UTC instant before which logins are suppressed, or None."""
        ...

    async def set_blocked_until(self, tenant: str, until: datetime | None) -> bool:
        """Store (or clear) the backoff; False when it could not be written (#133)."""
        ...

    async def clear(self, tenant: str) -> None:
        """Drop the stored session settings (#133); keeps any challenge backoff."""
        ...


def _is_regular_file(path: Path) -> bool:
    """True only for a real file, never for a symlink.

    The legacy session path is relative to the process working directory, so
    anything able to write there could point it at another file, and reading a
    followed link would treat arbitrary JSON as a session. `Path.is_file()`
    follows links, so it is not enough on its own.

    The unlink side needs no such protection — `os.unlink` removes the
    directory entry and never follows a link — so the guard there is only
    politeness about not deleting someone else's link.
    """
    return path.is_file() and not path.is_symlink()


def challenge_backoff_until() -> datetime:
    """Return the UTC instant a day out, for a login Instagram itself refused.

    Use this when the verdict is unambiguous — challenge, 2FA, bad
    credentials — since retrying sooner only re-triggers it.
    """
    return datetime.now(UTC) + timedelta(hours=CHALLENGE_BACKOFF_HOURS)


def transient_backoff_until() -> datetime:
    """Return the UTC instant an hour out, for a login that never reached a verdict.

    Network errors, throttling and publish timeouts get the short backoff: the
    cause may already be gone, so a full day would be too wide a blast radius.
    """
    return datetime.now(UTC) + timedelta(hours=TRANSIENT_BACKOFF_HOURS)


class FileSessionStore:
    """JSON file session store (single-tenant standalone default).

    #133: files are created 0600 in a 0700 directory, and all file I/O runs in a
    worker thread so it never blocks the event loop.
    """

    # Relative path the loader used as default before #133.
    LEGACY_DEFAULT_PATH = "instasession.json"

    def __init__(self, path: str | None = None) -> None:
        """Store the session at ``path``, or under the user cache when omitted.

        With no path, the location is ``$XDG_CACHE_HOME/publisher_v2/`` (falling
        back to ``~/.cache``) and the pre-#133 relative default is remembered as
        a one-time migration source, pinned to the working directory as it is at
        construction time.

        Args:
            path: Explicit session file path, usually ``session_file`` from config.
        """
        self._legacy_path: Path | None = None
        if not path:
            base = os.environ.get("XDG_CACHE_HOME") or os.path.join(Path.home(), ".cache")
            path = os.path.join(base, "publisher_v2", "instagram_session.json")
            # Pinned to the working directory at construction: a bare relative
            # path would otherwise be re-resolved against whatever the CWD
            # happens to be at call time. abspath, not resolve: resolve()
            # follows symlinks, which would bake the *target* of a planted link
            # into the path and defeat the symlink check at the point of use.
            self._legacy_path = Path(os.path.abspath(self.LEGACY_DEFAULT_PATH))
        self._path = Path(path)

    def _blocked_path(self) -> Path:
        return self._path.with_suffix(self._path.suffix + ".blocked")

    def _write_private(self, target: Path, text: str) -> None:
        """Write ``text`` 0600 atomically: temp file in the same directory, fsync, replace."""
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        # O_EXCL: the name is random, but refusing to reuse an existing path
        # is free and removes the symlink/clobber case entirely.
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)

    def _load_sync(self) -> tuple[dict[str, Any] | None, bool]:
        """Return (settings, migrated_from_legacy)."""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
            except (OSError, json.JSONDecodeError):
                return None, False
            return (data if isinstance(data, dict) else None), False
        # #133: carry over a session stored at the old relative default once, so
        # the move to $XDG_CACHE_HOME does not force a fresh password login. The
        # plaintext legacy file is removed once the copy is written.
        if self._legacy_path is not None and _is_regular_file(self._legacy_path):
            try:
                legacy = json.loads(self._legacy_path.read_text())
            except (OSError, json.JSONDecodeError):
                return None, False
            if isinstance(legacy, dict):
                self._write_private(self._path, json.dumps(legacy))
                self._legacy_path.unlink(missing_ok=True)
                return legacy, True
        return None, False

    async def load(self, tenant: str) -> dict[str, Any] | None:
        """Read the session file, migrating the pre-#133 location on first use.

        ``tenant`` is ignored — a file store holds a single standalone session.
        Returns None on unreadable or non-JSON-object content rather than
        raising, so a corrupt file degrades to a password login.
        """
        try:
            data, migrated = await asyncio.to_thread(self._load_sync)
        except OSError:
            log_json(logger, logging.WARNING, "instagram_session_load_failed", exc_info=True)
            return None
        if migrated:
            log_json(logger, logging.INFO, "instagram_session_legacy_migrated")
        return data

    async def save(self, tenant: str, settings: dict[str, Any]) -> None:
        """Write the settings 0600 and atomically; log and continue on OSError.

        ``tenant`` is ignored — a file store holds a single standalone session.
        """
        try:
            await asyncio.to_thread(self._write_private, self._path, json.dumps(settings))
        except OSError:
            log_json(logger, logging.WARNING, "instagram_session_save_failed", exc_info=True)

    def _clear_sync(self) -> None:
        self._path.unlink(missing_ok=True)
        # Never resurrect an expired session from the pre-#133 location — but
        # only ever unlink a real file there. See _is_regular_file.
        if self._legacy_path is not None and _is_regular_file(self._legacy_path):
            self._legacy_path.unlink(missing_ok=True)

    async def clear(self, tenant: str) -> None:
        """Delete the session file and any legacy copy; the backoff file survives.

        Removing the legacy copy too stops an expired session being resurrected
        from the pre-#133 path on the next load.
        """
        try:
            await asyncio.to_thread(self._clear_sync)
        except OSError:
            log_json(logger, logging.WARNING, "instagram_session_clear_failed", exc_info=True)

    def _get_blocked_sync(self) -> datetime | None:
        try:
            return datetime.fromisoformat(self._blocked_path().read_text().strip())
        except (OSError, ValueError):
            return None

    async def get_blocked_until(self, tenant: str) -> datetime | None:
        """Return the backoff deadline from the sidecar ``.blocked`` file, or None.

        A missing or unparsable file reads as "not blocked".
        """
        return await asyncio.to_thread(self._get_blocked_sync)

    def _set_blocked_sync(self, until: datetime | None) -> None:
        if until is None:
            self._blocked_path().unlink(missing_ok=True)
        else:
            self._write_private(self._blocked_path(), until.isoformat())

    async def set_blocked_until(self, tenant: str, until: datetime | None) -> bool:
        """Write the backoff deadline, or remove it when ``until`` is None.

        Returns False if the write failed (#133), so the caller can tell that
        the backoff is not actually being enforced.
        """
        try:
            await asyncio.to_thread(self._set_blocked_sync, until)
            return True
        except OSError:
            log_json(logger, logging.WARNING, "instagram_backoff_save_failed", exc_info=True)
            return False


def _fernet_from_secret(secret: str):
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


class DbSessionStore:
    """Postgres-backed session store: one encrypted row per tenant."""

    def __init__(self, session_factory: Any, secret: str) -> None:
        """Bind the store to an async SQLAlchemy session factory and a Fernet key.

        Args:
            session_factory: Async context-manager factory yielding a DB session.
            secret: Passphrase the encryption key is derived from; typically the
                web session secret. It is never stored or logged.
        """
        self._session_factory = session_factory
        self._fernet = _fernet_from_secret(secret)

    async def _get_row(self, session: Any, tenant: str):
        from sqlalchemy import select

        from publisher_v2.db.models import InstagramSession

        return (
            await session.execute(select(InstagramSession).where(InstagramSession.tenant == tenant))
        ).scalar_one_or_none()

    async def load(self, tenant: str) -> dict[str, Any] | None:
        """Decrypt and return the tenant's stored settings, or None.

        None covers every failure mode — no row, a cleared blob, a key that no
        longer decrypts the blob, or a database error — so a rotated secret
        costs a fresh login instead of breaking the publish.
        """
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
        """Encrypt the settings and upsert the tenant's row, inserting if absent.

        Any database or encryption failure is logged and swallowed; the session
        simply does not survive the restart.
        """
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

    async def clear(self, tenant: str) -> None:
        """Blank the tenant's session blob, keeping the row and its backoff.

        The row survives so ``blocked_until`` is not lost along with the
        session. Failures are logged and swallowed.
        """
        try:
            async with self._session_factory() as session:
                row = await self._get_row(session, tenant)
                if row is not None:
                    row.session_blob = ""
                    row.updated_at = datetime.now(UTC)
                    await session.commit()
        except Exception:
            log_json(logger, logging.WARNING, "instagram_session_clear_failed", exc_info=True)

    async def get_blocked_until(self, tenant: str) -> datetime | None:
        """Return the tenant's backoff deadline, or None when unset or unreadable.

        A database error reads as "not blocked" and is deliberately not logged,
        since this is consulted on every publish attempt.
        """
        try:
            async with self._session_factory() as session:
                row = await self._get_row(session, tenant)
            return row.blocked_until if row is not None else None
        except Exception:
            return None

    async def set_blocked_until(self, tenant: str, until: datetime | None) -> bool:
        """Store (or clear with None) the tenant's backoff, creating the row if needed.

        Returns False on failure (#133) so the caller can tell that the backoff
        is not actually being enforced.
        """
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
            return True
        except Exception:
            log_json(logger, logging.WARNING, "instagram_backoff_save_failed", exc_info=True)
            return False


def build_session_store(session_file: str | None = None) -> SessionStore:
    """Pick the store: Postgres when available (survives restarts), else file."""
    from publisher_v2.db import get_session_factory

    secret = (os.environ.get("WEB_SESSION_SECRET") or os.environ.get("SECRET_KEY") or "").strip()
    factory = get_session_factory()
    if factory is not None and secret:
        return DbSessionStore(factory, secret)
    return FileSessionStore(session_file)
