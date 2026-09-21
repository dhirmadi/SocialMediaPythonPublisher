"""PUB-047 #186 / AC7: Postgres engine gets bounded connect + command timeouts.

The engine is never actually connected here — ``create_async_engine`` is patched at
the name ``db/__init__.py`` imported it under, and the assertion is on the kwargs
the call was made with.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import publisher_v2.db as db
from publisher_v2.config.runtime_settings import load_runtime_settings


@pytest.fixture(autouse=True)
def _restore_db_globals():
    """``init_db`` writes module-level globals; the suite runs in random order."""
    engine, factory = db._engine, db._session_factory  # noqa: SLF001 — test isolation
    yield
    db._engine, db._session_factory = engine, factory  # noqa: SLF001 — test isolation


def test_init_db_passes_connect_and_command_timeout_from_runtime_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Credential-free on purpose: a user:password@host URL here trips the secret scanner
    # (PUB-047 review / PUB-055). The engine is never connected, so no credentials are needed.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost/appdb")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "3.5")
    monkeypatch.setenv("DB_COMMAND_TIMEOUT_SECONDS", "7.25")
    settings = load_runtime_settings()

    with patch("publisher_v2.db.create_async_engine", MagicMock()) as create_engine:
        db.init_db(settings=settings)

    assert create_engine.call_count == 1
    connect_args = create_engine.call_args.kwargs.get("connect_args")
    assert connect_args == {"timeout": 3.5, "command_timeout": 7.25}


# ---------------------------------------------------------------------------
# Coverage tests for the engine lifecycle helpers (PUB-047 stage C).
# No real Postgres is involved: the engine is an AsyncMock-driven double.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_health_cache(monkeypatch: pytest.MonkeyPatch):
    """``check_connectivity`` memoises its result in a module global."""
    monkeypatch.setattr(db, "_health_cache", None)


def _fake_engine(execute_side_effect: BaseException | None = None) -> MagicMock:
    """Build an engine double whose ``connect()`` works as an async context manager."""
    conn = MagicMock()
    conn.execute = AsyncMock(side_effect=execute_side_effect)
    engine = MagicMock()
    engine.dispose = AsyncMock()
    engine.connect.return_value.__aenter__.return_value = conn
    engine.connect.return_value.__aexit__.return_value = False
    return engine


async def test_dispose_engine_disposes_and_clears_module_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _fake_engine()
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_session_factory", MagicMock())

    await db.dispose_engine()

    engine.dispose.assert_awaited_once_with()
    assert db.get_engine() is None
    assert db.get_session_factory() is None


async def test_dispose_engine_is_a_noop_when_db_was_never_initialised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "_engine", None)
    monkeypatch.setattr(db, "_session_factory", None)

    await db.dispose_engine()  # must not raise
    await db.dispose_engine()  # idempotent

    assert db.get_engine() is None
    assert db.get_session_factory() is None


async def test_check_connectivity_is_false_when_db_was_never_initialised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "_engine", None)

    assert await db.check_connectivity() is False
    assert db._health_cache is None  # noqa: SLF001 — a missing engine must not poison the cache


async def test_check_connectivity_runs_select_1_and_returns_true(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _fake_engine()
    monkeypatch.setattr(db, "_engine", engine)

    assert await db.check_connectivity() is True

    conn = engine.connect.return_value.__aenter__.return_value
    conn.execute.assert_awaited_once()
    assert str(conn.execute.await_args.args[0]) == "SELECT 1"
    ok, _checked_at = db._health_cache  # noqa: SLF001 — asserting the memoised result
    assert ok is True


async def test_check_connectivity_returns_false_when_the_connection_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _fake_engine(execute_side_effect=OSError("connection refused"))
    monkeypatch.setattr(db, "_engine", engine)

    assert await db.check_connectivity() is False

    ok, _checked_at = db._health_cache  # noqa: SLF001 — the failure is memoised too
    assert ok is False


async def test_check_connectivity_serves_a_fresh_cached_result_without_touching_the_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fake_engine()
    monkeypatch.setattr(db, "_engine", engine)
    monkeypatch.setattr(db, "_health_cache", (False, time.monotonic()))

    assert await db.check_connectivity() is False
    engine.connect.assert_not_called()


async def test_check_connectivity_rechecks_once_the_cached_result_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _fake_engine()
    monkeypatch.setattr(db, "_engine", engine)
    stale_at = time.monotonic() - (db._HEALTH_CHECK_TTL_SECONDS + 1)  # noqa: SLF001 — TTL is the spec'd boundary
    monkeypatch.setattr(db, "_health_cache", (False, stale_at))

    assert await db.check_connectivity() is True
    engine.connect.assert_called_once_with()


def test_init_db_requires_an_explicit_settings_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    """PUB-047 review item 3: the ``load_runtime_settings()`` constructor fallback is gone.

    Every call site must hand ``init_db`` the process-wide snapshot (#143), so a
    zero-arg call is a ``TypeError`` rather than a second, divergent env read.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost/appdb")

    with patch("publisher_v2.db.create_async_engine", MagicMock()), pytest.raises(TypeError):
        db.init_db()
