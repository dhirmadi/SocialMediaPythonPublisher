# PUB-083: Close the Tenant Factory Shutdown Race

| Field | Value |
|-------|-------|
| **ID** | PUB-083 |
| **Category** | Web UI |
| **Priority** | P2 |
| **Effort** | S |
| **Status** | Proposal |
| **Dependencies** | None (lands before PUB-053's #197 work, see Scope) |

## User Story

As the platform maintainer, I want no tenant service to outlive the shutdown that was meant to close
it, so that a request racing the lifespan shutdown cannot leak storage/HTTP clients or drop
storage-ops metrics.

## Problem

Tracked in [#174](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/174). Verified against `main` at `c66f47a`:

1. **Drop then close leaves a window.** `web/app.py:180-182` runs `factory = reset_tenant_service_factory()`
   and then `await factory.shutdown()`; the comment at `:172-179` records the race as accepted.
2. **Nothing refuses a late request.** `web/middleware.py:30-39` `_tenant_service_factory` builds a new
   `_FACTORY` whenever the global is `None`, and `reset_tenant_service_factory` (`:47-57`) sets it to
   `None`. There is no shutting-down state, so a request arriving mid-shutdown installs a second factory
   whose services no shutdown ever closes.
3. **The factory itself has no closed state.** `web/tenant_factory.py:63-101`: no lock, no flag.
   `shutdown()` iterates `self._data.values()` across `await`s, so a request still holding the dropped
   factory can insert an entry mid-loop (`RuntimeError: OrderedDict mutated during iteration`, swallowed
   by the lifespan's `except` at `app.py:183`, leaving the remaining services open) or insert after
   `clear()` — either way an orphaned service.

## Decision

A request that reaches tenant resolution after shutdown has begun gets **503** with the existing
`{"error": "Service unavailable"}` body — the option #174 calls cleaner. Serving it from the dropped,
closing factory is rejected: it hands a request closed clients. `/health*` and standalone mode are
untouched (the middleware skips them today).

Owner decisions, 2026-09-27:
- **No `Retry-After` header.** The process is exiting, so retrying against the same instance does not help.
- **Priority P2**, not P3, because this item is a prerequisite for PUB-053's #197 work.

## Scope

**In scope:**
- `core/exceptions.py`: `TenantFactoryClosedError(SocialMediaPublisherError)`.
- `TenantServiceFactory`: a `_closed` flag. `shutdown()` sets it first, swaps `_data` for an empty dict,
  then closes the swapped entries; a second call is a no-op. `get_service` raises
  `TenantFactoryClosedError` when closed on entry, and re-checks after every `await` it makes: a service
  built while shutdown ran is closed, not cached, and the call raises.
- `web/middleware.py`: a module `_CLOSED` flag. New `close_tenant_service_factory()` sets it and
  drops/returns `_FACTORY` (replaces the lifespan's use of `reset_tenant_service_factory`). New
  `open_tenant_service_factory()` clears it. `_tenant_service_factory` raises `TenantFactoryClosedError`
  while closed and never builds; `tenant_middleware` maps it to 503.
- `web/app.py`: lifespan startup calls `open_tenant_service_factory()`; shutdown calls
  `close_tenant_service_factory()`; the `:165-179` comment is rewritten to state the 503 behaviour.
- Test isolation: `reset_tenant_service_factory()` keeps its test contract and also clears `_CLOSED`;
  a new autouse fixture in `publisher_v2/tests/conftest.py` calls it before and after every test, so a
  lifespan exited in one test cannot 503 a later one under `pytest-randomly`.

**Out of scope:**
- The per-tenant build lock and TTL extension (PUB-053 #197, closing #169) and constructing the service
  in a thread (PUB-053 #201). **Ordering:** land this item first. It is small, self-contained, and gives
  #197/#201 an invariant to keep. The designs do not conflict: the closed flag is factory-wide and is
  checked after acquiring #197's per-tenant lock and after #201's threaded build; #197's lock never
  guards `shutdown()`, so shutdown cannot block behind a slow build. PUB-053's handoff must name this
  item's tests as regression tests.
- Draining in-flight requests (uvicorn already does this before `lifespan.shutdown`).

## Acceptance Criteria

- AC1: Given the middleware factory has been closed, when `_tenant_service_factory(settings)` is called,
  then it raises `TenantFactoryClosedError` and `_existing_tenant_service_factory()` stays `None`.
- AC2: Given a lifespan whose shutdown is paused between the drop and `factory.shutdown()` completing,
  when an orchestrator-mode request arrives, then it gets 503 with `{"error": "Service unavailable"}`,
  no second factory is built, and every service the first factory built ends `closed`.
- AC3: Given a factory whose `get_service` is suspended in an `await` (stale-service close), when
  `shutdown()` runs to completion and `get_service` resumes, then it raises `TenantFactoryClosedError`
  and no service it built is left unclosed or in `_data`.
- AC4: Given a factory with cached services, when `shutdown()` is called twice, then each service's
  `aclose` ran exactly once and the second call does not raise.
- AC5: Given a closed factory, when `get_service` is called, then it raises `TenantFactoryClosedError`
  without constructing a service.
- AC6: Given one lifespan has exited, when a second `TestClient(app)` lifespan starts and serves a
  tenant request, then it succeeds with a new factory (existing test stays green).
- AC7: Given `close_tenant_service_factory()` was called, when `reset_tenant_service_factory()` runs,
  then a subsequent `_tenant_service_factory(settings)` builds a factory (test isolation contract).
- AC8: Given this item ships, when its implementing PR merges, then #174 is closed with `Closes #174`
  in the PR body.

## Test-first targets

| AC | Test (exact function) |
|----|------|
| AC1 | `publisher_v2/tests/test_tenant_factory_shutdown_race.py::test_closed_middleware_factory_refuses_to_build` |
| AC2 | `publisher_v2/tests/test_tenant_factory_shutdown_race.py::test_request_during_lifespan_shutdown_gets_503_and_orphans_nothing` |
| AC3 | `publisher_v2/tests/test_tenant_factory_shutdown_race.py::test_get_service_resumed_after_shutdown_closes_what_it_built` |
| AC4 | `publisher_v2/tests/test_tenant_factory_shutdown_race.py::test_shutdown_is_idempotent_and_closes_each_service_once` |
| AC5 | `publisher_v2/tests/test_tenant_factory_shutdown_race.py::test_closed_factory_get_service_raises_without_building` |
| AC6 | `publisher_v2/tests/test_tenant_factory_eviction.py::TestProcessFactorySingleton::test_a_second_lifespan_does_not_reuse_the_shut_down_factory` (existing) |
| AC7 | `publisher_v2/tests/test_tenant_factory_shutdown_race.py::test_reset_reopens_a_closed_middleware_factory` |

Mock only the orchestrator `ConfigSource` and `WebImageService` (as `test_tenant_factory_eviction.py`
does); pause shutdown with an `asyncio.Event` inside a fake `aclose`, not with sleeps.

## Risks

- **A test relies on building a factory after a lifespan exit without `with TestClient`.** The autouse
  reset covers this; run the suite with several `--randomly-seed` values before merge.
- **503 during shutdown is a behaviour change.** It only affects requests uvicorn has not drained, in a
  process that is exiting.

## References

- [#174](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/174) — this item's issue (closed here)
- PUB-053 — per-tenant lock (#197, closes #169) and threaded build (#201); not closed here
- #143 (factory singleton, settings snapshot), #86 (close on replace/evict), PR #162 audit (found the race)
