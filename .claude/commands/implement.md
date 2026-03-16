---
description: Spec-based TDD implementation of a roadmap item from hardened spec
allowed-tools: Bash, Read, Write, Edit
---

# Implement Roadmap Item (Spec-Based TDD)

You are implementing a roadmap item that has been specified, reviewed, and hardened in Cursor. The spec is your contract.

## Input

The user provides a roadmap item path: `$ARGUMENTS`

Example: `docs_v2/roadmap/PUB-023_something.md`

If no path is provided, ask for the roadmap item path under `docs_v2/roadmap/`.

## Workflow

### Step 1: Read the Contract

1. Read the roadmap item spec: `docs_v2/roadmap/PUB-NNN_slug.md`
   - Extract: goals, non-goals, acceptance criteria, implementation notes
2. Read the handoff document: `docs_v2/roadmap/PUB-NNN_handoff.md`
   - Contains: implementation order, test-first targets, mock boundaries, files to touch

If the handoff doc doesn't exist, read the roadmap item spec directly and plan from it.

**Stop and report** if:
- The roadmap item path doesn't exist
- There's no spec doc
- Acceptance criteria are vague or untestable (ask the user to run `/product/harden` in Cursor first)

### Step 2: Create Implementation Plan

Create an implementation plan (inline or as `docs_v2/roadmap/PUB-NNN_plan.yaml`):

- `version`, `roadmap_id` (PUB-NNN), `summary`
- `repo_constraints` (allowed/excluded paths)
- `acceptance_criteria` (from the spec)
- `tasks` (ordered, with file paths)
- `quality_gates` (coverage minimums, safety checks)

Keep the plan minimal — only what's needed to satisfy the ACs.

### Step 3: Write Tests First (TDD)

Strictly follow the TDD cycle:

**Write failing tests**
- Create or update test files under `publisher_v2/tests/`
- Write one test per acceptance criterion (minimum)
- Tests must assert the spec'd behavior, not implementation details
- Use existing fixtures and mocks where available (check `publisher_v2/tests/conftest.py`)
- Run tests to confirm they fail: `uv run pytest -v --tb=short -k "test_<relevant_name>"`

### Step 4: Implement Code to Make Tests Pass

- Write the minimum code to make the failing tests pass
- Stay within `publisher_v2/src/publisher_v2/` following the existing layout:
  - Config: `config/`
  - Domain/orchestration: `core/`
  - External services: `services/`
  - Utilities: `utils/`
  - Web: `web/`
- Reuse existing patterns — don't reinvent

### Step 5: Run All Quality Gates

```bash
uv run ruff format .
uv run ruff check --fix .
uv run ruff check .
uv run mypy . --ignore-missing-imports --exclude=venv --exclude=env
uv run pytest -v --cov=publisher_v2/src/publisher_v2 --cov-report=term-missing --tb=short
```

Verify coverage gates: ≥80% on affected modules, ≥85% overall.

### Step 6: Create Summary

Create `docs_v2/roadmap/PUB-NNN_summary.md`:

```markdown
# PUB-NNN — <Name>: Implementation Summary

**Status:** Implementation Complete
**Date:** <today>

## Files Changed
- `publisher_v2/src/publisher_v2/<file>` — <what changed>
- `publisher_v2/tests/test_<file>.py` — <tests added>

## Acceptance Criteria
- [x] AC1 — <description> (test: `test_<name>`)
- [x] AC2 — ...

## Test Results
<paste test output summary>

## Quality Gates
- Format: ✅
- Lint: ✅
- Type check: ✅
- Tests: N passed, 0 failed
- Coverage: N% overall

## Notes
<any implementation decisions or deviations from spec>
```

## Non-Negotiables

- **Preview safety:** Preview mode must never publish, archive, or mutate state.
- **No secrets:** Never hard-code tokens, passwords, or API keys.
- **Async hygiene:** No blocking calls in async paths without `asyncio.to_thread()`.
- **Web auth:** Mutating endpoints require auth per `publisher_v2.web.auth`.
- **Backward compatibility:** Do not break CLI flags, endpoint contracts, or config semantics.

## Critical Rules

- **The spec is the contract.** If something is ambiguous, read the spec again. If still ambiguous, ask the user.
- **Tests before code.** Always. No exceptions.
- **Never adjust tests to match incorrect code.** If a test fails, determine whether the test or the code is wrong by checking the spec.
- **Minimal implementation.** Write the simplest code that satisfies the ACs. No speculative features.
