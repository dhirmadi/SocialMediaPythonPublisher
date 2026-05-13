"""Persistent posted-image state, written atomically with an advisory lock.

The state file stores SHA-256 hashes of published image bytes plus
provider-supplied content hashes used for fast dedup. Two correctness
invariants:

  - Reads must never return a partially-written file (atomic-rename writer).
  - Concurrent writers (two workers, or CLI + web) must not lose updates
    (``fcntl.flock`` advisory lock around the whole read-modify-write cycle).

A failed write is logged at WARNING and re-raised — callers must decide what
"failed to remember we published" means in their flow. The previous behavior
of silently swallowing the error meant the next workflow run would happily
re-publish the image.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from collections.abc import Iterator
from pathlib import Path

logger = logging.getLogger("publisher_v2.state")


def _cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(Path.home(), ".cache")
    path = Path(base) / "publisher_v2"
    path.mkdir(parents=True, exist_ok=True)
    return path / "posted.json"


def _lock_path() -> Path:
    return _cache_path().with_suffix(".json.lock")


@contextlib.contextmanager
def _file_lock() -> Iterator[None]:
    """Cross-process advisory lock around the posted-state file.

    On platforms without ``fcntl`` (Windows) this degrades to a thread-local
    no-op; the project targets darwin/linux operationally.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover — non-Unix
        yield
        return

    lock_path = _lock_path()
    fp = open(lock_path, "a+")  # noqa: SIM115 — closed in finally
    try:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(Exception):
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
        fp.close()


def _load_state_locked() -> dict[str, object]:
    """Load posted state (caller holds the file lock)."""
    fp = _cache_path()
    if not fp.exists():
        return {}
    try:
        raw = fp.read_text()
    except OSError:
        logger.warning("posted_state_read_failed", exc_info=True)
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("posted_state_corrupt_json", exc_info=True)
        return {}

    if not isinstance(data, dict):
        # Legacy V1 list-format was removed per code-review. Treat anything
        # non-dict as corrupt.
        logger.warning("posted_state_unexpected_shape", extra={"type": type(data).__name__})
        return {}

    state: dict[str, object] = {}
    hashes = data.get("hashes")
    if isinstance(hashes, list):
        state["hashes"] = [str(x) for x in hashes]
    content_hashes = data.get("dropbox_content_hashes")
    if isinstance(content_hashes, list):
        state["dropbox_content_hashes"] = [str(x) for x in content_hashes]
    return state


def _save_state_locked(state: dict[str, object]) -> None:
    """Atomic write: serialise to a sibling temp file then ``os.replace``."""
    fp = _cache_path()
    tmp = fp.with_suffix(".json.tmp")
    payload = json.dumps(state, sort_keys=True).encode("utf-8")
    try:
        with open(tmp, "wb") as out:
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, fp)
    except OSError:
        logger.warning("posted_state_write_failed", exc_info=True)
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _load_state() -> dict[str, object]:
    with _file_lock():
        return _load_state_locked()


def load_posted_hashes() -> set[str]:
    state = _load_state()
    hashes = state.get("hashes")
    if isinstance(hashes, list):
        return {str(x) for x in hashes}
    return set()


def save_posted_hash(hash_value: str) -> None:
    if not hash_value:
        return
    with _file_lock():
        state = _load_state_locked()
        hashes = state.get("hashes")
        if not isinstance(hashes, list):
            hashes = []
        if hash_value in hashes:
            return
        hashes.append(hash_value)
        state["hashes"] = sorted({str(x) for x in hashes})
        _save_state_locked(state)


def load_posted_content_hashes() -> set[str]:
    state = _load_state()
    content_hashes = state.get("dropbox_content_hashes")
    if isinstance(content_hashes, list):
        return {str(x) for x in content_hashes}
    return set()


def save_posted_content_hash(hash_value: str) -> None:
    if not hash_value:
        return
    with _file_lock():
        state = _load_state_locked()
        content_hashes = state.get("dropbox_content_hashes")
        if not isinstance(content_hashes, list):
            content_hashes = []
        if hash_value in content_hashes:
            return
        content_hashes.append(hash_value)
        state["dropbox_content_hashes"] = sorted({str(x) for x in content_hashes})
        _save_state_locked(state)
