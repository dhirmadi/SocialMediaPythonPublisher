---
name: test-isolation-review-traps
description: Review traps for #135 test-order-independence work — pytest-randomly default-on, `import conftest`, limiter/http-client global resets
metadata:
  type: project
---

Traps found reviewing PR #156 (issue #135, order-independent suite). Verify before repeating.

- **`import conftest` in a test module only works by accident of layout.** `publisher_v2/tests/` has no
  `__init__.py` and pytest uses default `prepend` import mode, so the root conftest is registered as
  top-level `conftest` (verified: single module object, `web/conftest.py` becomes `web.conftest`, no
  collision). Adding `publisher_v2/tests/__init__.py` or `--import-mode=importlib` breaks it at collection.
- **`pytest-randomly` is default-on once installed.** Nothing in `addopts` pins a seed, so every local
  run, the `.claude/hooks/pre-commit-tests.sh` gate and `.github/workflows/code-quality.yml` run a fresh
  random order. Mitigation that already exists: the seed is printed in the pytest header (CI does not use
  `--no-header`). Check whether docs mention it — as of #135 nothing in docs_v2/CLAUDE.md/AGENTS.md does.
- **Root-conftest global resets are masks, and their scope is module-wide, not container-wide.**
  `reset_web_rate_limiters()` scans `vars(publisher_v2.web.app)` by `isinstance(SlidingWindowLimiter)`.
  A limiter created in a router module, or held in a list/dict, is invisible to both the reset and its
  guard test. Same shape for `reset_shared_http_client()`, which nulls `services/_http._client` without
  `await aclose()` (safe today: httpx `AsyncClient` has no `__del__`, and the only test that builds one
  fakes `httpx.AsyncClient`).
- **`_http._client_lock` is a module-level `asyncio.Lock`** re-entered by every test now that `_client`
  is reset per test. Verified safe on CPython 3.12: `Lock.acquire()`'s uncontended fast path never calls
  `_get_loop()`, so it does not bind to a dead event loop.
- **Tests that assert "state is clean at start" under an autouse reset are self-fulfilling.**
  `test_the_shared_http_client_does_not_survive_a_test`'s opening `assert _http._client is None` can only
  ever fail if the autouse fixture is deleted — it is not a guard, the last two lines are the real test.

Related: [[coverage-gate-review-traps]], [[layering-guard-review-traps]].
