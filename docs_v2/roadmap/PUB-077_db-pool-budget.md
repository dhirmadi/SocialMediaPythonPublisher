# PUB-077: Fit the DB Connection Pool into the Shared 20-Connection Postgres

| Field | Value |
|-------|-------|
| **ID** | PUB-077 |
| **Category** | Ops |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Proposal |
| **Dependencies** | PUB-047 |

## User Story

As a platform maintainer, I want the publisher's Postgres pool to be small, configurable and logged, so that the publisher and the orchestrator can share one 20-connection database without either of them hitting `TooManyConnectionsError`.

## Problem

Since 2026-09-27 (release v38), production `fetlife-production-org` uses the orchestrator's Postgres `postgresql-defined-25454` (essential-0, 20 connections). Both apps now draw from that one budget ([#248](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/248)).

- `db/__init__.py:62-67` creates the engine with hard-coded `pool_size=3, max_overflow=5` (`pool_pre_ping=True` is already set).
- `web/app.py:122` calls `init_db` once per uvicorn worker. The Procfile passes no `--workers`, so uvicorn uses `WEB_CONCURRENCY`, which is 2 in production. The web dyno can therefore open 2 × 8 = **16** connections.
- The orchestrator holds about 10 idle connections, and during the 2026-09-27 bot scan it went past that and hit `TooManyConnectionsError` (#246). In the worst case the two apps need 10 + 16 = 26 > 20. The orchestrator is the control plane, so when it fails every tenant fails.
- Other things draw on the same budget and appear in no calculation today:
  - the release-phase `alembic upgrade`, one connection with `NullPool` (`alembic/env.py:74`), which runs while the old dynos are still serving;
  - any `heroku run` of the CLI, since `app.py:113` calls `init_db` and builds its own pool;
  - `pg:psql` or ad-hoc asyncpg sessions used for inspection.
- The startup log line at `db/__init__.py:75` has the pool numbers typed in as text, so it would report the wrong values as soon as they become configurable.

## Desired Outcome

By default each worker opens at most 3 connections (1 pooled + 2 overflow), so the production web dyno opens at most 6. Operators can change the pool size, overflow and checkout timeout through environment variables, which are validated at startup and documented. Each worker logs the values it actually uses. When the pool runs out, callers wait a bounded time and the failure is logged, not silently swallowed. The documented connection budget for the shared database leaves room to spare.

## Scope

**In scope:**
- `RuntimeSettings` fields `db_pool_size` (default 1), `db_max_overflow` (default 2) and `db_pool_timeout_seconds` (default 10.0), parsed in `load_runtime_settings` from `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` and `DB_POOL_TIMEOUT_SECONDS`, next to the PUB-047 DB timeouts
- Validation: `db_pool_size >= 1`, `db_max_overflow >= 0`, `db_pool_timeout_seconds > 0`. A bad value raises `ConfigurationError` when the settings are built, the same way `_reject_non_positive_timeout` does
- `init_db` passes `pool_size`, `max_overflow` and `pool_timeout` from `settings`. It must not read `os.environ` directly (#143 snapshot rule)
- The startup log line reports the effective `pool_size`, `max_overflow` and `pool_timeout`
- A pool checkout timeout (`sqlalchemy.exc.TimeoutError`) is logged as a structured event on every DB path that currently degrades gracefully
- `docs_v2/05_Configuration/CONFIGURATION.md` rows for the three variables, plus a short connection-budget note: the publisher's share is `WEB_CONCURRENCY × (DB_POOL_SIZE + DB_MAX_OVERFLOW)`, plus 1 per release phase and 1 pool per one-off CLI dyno

**Out of scope:**
- `pool_recycle`. Heroku Postgres has no fixed idle cutoff to stay under, credential rotation changes `DATABASE_URL` and restarts the dynos, and `pool_pre_ping` already handles dead connections. Revisit only if a concrete timeout (router, PgBouncer) turns up
- Capping the orchestrator's own pool. That is filed as a companion issue in `dhirmadi/platform-orchestrator`, the contract owner
- PgBouncer or a dedicated database for the publisher
- Changing `WEB_CONCURRENCY`

## Acceptance Criteria

- AC1: Given no pool env vars, when `init_db` runs, then `create_async_engine` is called with `pool_size=1`, `max_overflow=2`, `pool_timeout=10.0` and `pool_pre_ping=True`, and the PUB-047 `connect_args` are unchanged
- AC2: Given `DB_POOL_SIZE=2`, `DB_MAX_OVERFLOW=0` and `DB_POOL_TIMEOUT_SECONDS=5`, when settings load and `init_db` runs, then the engine receives exactly those values
- AC3: Given `DB_POOL_SIZE=0`, or `DB_MAX_OVERFLOW=-1`, or `DB_POOL_TIMEOUT_SECONDS=0`, when `load_runtime_settings()` runs, then it raises `ConfigurationError` naming the field
- AC4: Given any pool settings, when `init_db` runs, then the startup log line contains the effective `pool_size`, `max_overflow` and `pool_timeout`, not literals
- AC5: Given an engine limited to one connection (`pool_size=1, max_overflow=0`, short `pool_timeout`) whose only connection is checked out, when a caption-history or Instagram-session call needs a connection, then it does not hang past `pool_timeout`, and a structured log event names the pool timeout
- AC6: Given an engine with `pool_size=1, max_overflow=2`, when three sessions are used at once (for example a three-platform publish claim followed by the release gather), then all complete without a pool timeout
- AC7: Given the docs, when `CONFIGURATION.md` is read, then `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` and `DB_POOL_TIMEOUT_SECONDS` are listed with defaults, and the connection-budget formula is stated
- AC8 (operational, verified after deploy, not in CI): Given production at `WEB_CONCURRENCY=2` with default pool settings, when a publish runs, then `pg_stat_activity` for the publisher's application shows at most 6 connections and the shared database has at least 4 free
- AC9: Given this item ships, when its implementing PR merges, then #248 is closed with `Closes #248` in the PR body

## Implementation Notes

- Extend `publisher_v2/tests/test_db_connect_args.py`. It already patches `publisher_v2.db.create_async_engine` and checks its keyword arguments. Do not create a new test file for AC1 to AC4.
- AC5 and AC6 can run against a real SQLite engine with an explicit `QueuePool`, or against a fake pool. Mock only at the SQLAlchemy boundary, never inside the stores.
- `caption_store.py:93` and `instagram_session.py:305` catch broad `Exception`. Check that a pool `TimeoutError` there is logged with a distinct event name, and is not just folded into a generic "DB unavailable" path.
- Ten seconds for `pool_timeout` is shorter than SQLAlchemy's 30 s default, so a starved worker fails well before the web request budget. Reconsider this if the publish claim budget (`PUBLISH_CLAIM_TIMEOUT_SECONDS`, 10 s) turns out to need more headroom.

## Risks

- **Waiting on a small pool.** At 1+2 per worker, a busy multi-tenant worker could queue for a connection. Mitigations: AC6 covers the known concurrent paths, and operators can raise `DB_MAX_OVERFLOW` without a deploy while keeping to the budget formula.
- **Budget drift.** Raising `WEB_CONCURRENCY` later silently multiplies the publisher's share. The docs formula is the guard, and the startup log shows the per-worker numbers.

## Success Metrics

- No `TooManyConnectionsError` in either app's logs in the 30 days after deploy
- Publisher connections in `pg_stat_activity` at most 6 during publishes

## Related

- #248 — this item's issue (closed here)
- #246 / #247 — orchestrator connection exhaustion during the bot scan (context, already closed)
- PUB-047 — asyncpg connect/command timeouts, whose pattern this follows
- PUB-053 — shared-dyno isolation (related, does not cover DB pooling)
- Orchestrator companion issue: cap `org-prod`'s pool (to be filed in `dhirmadi/platform-orchestrator`, not closed here)
