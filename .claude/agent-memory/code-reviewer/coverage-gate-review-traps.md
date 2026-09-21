---
name: coverage-gate-review-traps
description: Coverage gate (#141) traps — cwd-relative coverage config silently disables source/fail_under; bare --cov honours [tool.coverage.run]; addopts fail_under breaks partial runs and -p no:cov; --no-cov is the remaining bypass
metadata:
  type: project
---

Facts verified 2026-09-20 on `fix/141-coverage-gate` rebased onto `integration/128` (pytest 8.4.2, pytest-cov 7.0.0, coverage 7.10.7).

- Bare `--cov` (no value) DOES honour `[tool.coverage.run] source`. `--cov=.` re-inflates with `publisher_v2/tests/*`. An explicit `--cov=<path>` overrides `source`.
- **Silent bypass (fixed):** coverage discovers its own config relative to CWD, not pytest's rootdir. `--cov-fail-under=85` now lives in `[tool.pytest.ini_options] addopts`, which IS rootdir-relative, so a subdirectory run fails correctly (verified: `cd publisher_v2 && pytest --cov` → FAIL at 53.73%). The *number* there is still wrong (tests included); only the gate is portable.
- Consequences of fail_under in addopts: any partial `--cov` run fails (use `--cov-fail-under=0` or `make test-cov-file FILE=…`), and **`pytest -p no:cov` hard-errors** with `unrecognized arguments: --cov-fail-under=85` — so does any env without pytest-cov. Documented in AGENTS.md.
- `--cov-fail-under=85` is inert with no `--cov` (plain `pytest` and `--collect-only` are fine; the pre-commit hook `uv run pytest -q --no-header --tb=short` is unaffected).
- **Remaining bypasses to check on any CI-workflow edit:** `--no-cov` (exits 0, gate never runs) and an explicit `--cov-fail-under=0`. `test_ci_runs_coverage_without_overriding_the_source_setting` does not forbid either.
- Nested-pytest-in-subprocess tests do not pollute parent totals when they set `COVERAGE_FILE`.
- Codecov step consumes `./coverage.xml` only; dropping `--cov-report=html` from CI broke nothing.

**Why:** #141 turned prose thresholds into an enforced gate; these are the ways the gate can be defeated or misfire.
**How to apply:** when reviewing anything touching coverage config or CI test commands, re-check cwd-relative discovery, grep for remaining `--cov=` usages (QUALITY_METRICS.md, docs_v2/10_Testing/README.md, .cursor/, .claude/), and check the workflow for `--no-cov`/`--cov-fail-under=0`.

Real figure 2026-09-20 on integration/128 + this branch: **88.75%**, 6451 stmts, 726 missing, 1337 passed / 1 skipped.
Under the 80% per-module bar (6): `web/service.py` 78, `config/web_env.py` 67, `tools/migrate_storage.py` 60, `db/__init__.py` 56, `services/instagram_session.py` 51, `tools/__main__.py` 0. `web/routers/auth.py` is exactly 80. (PR #160's body still lists the pre-rebase set, incl. middleware.py/middleware_csrf.py, now 94%/90%.)
`scripts/heroku_hetzner_clone.py` (429 stmts, has `publisher_v2/tests/test_scripts_heroku_hetzner_clone.py`) is no longer measured — deliberate, #141 prescribes the source list verbatim.
