---
description: Post-implementation quality verification for a roadmap item
allowed-tools: Bash, Read
---

# Verify Roadmap Item Implementation

Run all quality gates on a recently implemented roadmap item and produce a verification report.

## Input

The user provides a roadmap item path: `$ARGUMENTS`

Example: `docs_v2/roadmap/PUB-023_something.md`

If no path is provided, run verification on the entire codebase.

## Verification Pipeline

### 1. Read the spec

If a roadmap item path is provided:
- Read `docs_v2/roadmap/PUB-NNN_slug.md` (the spec) to get goals, acceptance criteria, and implementation notes
- Read `docs_v2/roadmap/PUB-NNN_summary.md` (if exists) to understand what was implemented

### 2. Run quality gates

Execute each gate sequentially. Report pass/fail for each:

```bash
# Gate 1: Format check
uv run ruff format --check .

# Gate 2: Lint
uv run ruff check .

# Gate 3: Type check
uv run mypy . --ignore-missing-imports --exclude=venv --exclude=env

# Gate 4: Tests
uv run pytest -v --tb=short

# Gate 5: Coverage
uv run pytest -v --cov=publisher_v2/src/publisher_v2 --cov-report=term-missing --tb=short
```

### 3. Acceptance criteria check (if roadmap item path provided)

For each acceptance criterion in the spec:
- Find the corresponding test(s)
- Verify the test passed
- Report: AC description → test name → PASS/FAIL/NOT TESTED

### 4. Spec drift check

Compare implementation against the spec:
- **Over-implementation:** Does the code do things not in the spec? Flag for review.
- **Under-implementation:** Does the code miss anything in the spec? Flag as failure.
- Report any drift with severity and suggested fix.

### 5. Security spot-check

Quick scan of recently changed files:
- No hard-coded secrets (API keys, tokens, passwords)
- No `print()` statements (should use structured logging)
- Preview mode guard present where needed
- Auth required on mutating web endpoints

### 6. Produce report

```markdown
# Verification Report — PUB-NNN

## Quality Gates
| Gate | Status | Details |
|------|--------|---------|
| Format | ✅/❌ | N files need formatting |
| Lint | ✅/❌ | N violations |
| Type check | ✅/❌ | N errors |
| Tests | ✅/❌ | N passed, N failed |
| Coverage | ✅/❌ | N% overall (threshold: 85%) |

## AC Verification (PUB-NNN)
| AC | Test | Result |
|----|------|--------|
| <AC description> | `test_<name>` | ✅/❌ |

## Spec Drift
| Type | Finding | Severity |
|------|---------|----------|
| Over/Under | <description> | error/warning |

## Security
| Check | Status |
|-------|--------|
| No hard-coded secrets | ✅/❌ |
| Structured logging | ✅/❌ |
| Preview safety | ✅/❌ |
| Auth on mutations | ✅/❌/N/A |

## Verdict: [ALL GATES PASS / NEEDS FIXES]

## Issues (if any)
1. <issue and how to fix>
```

If all gates pass, report: "Ready for delivery review in Cursor: `/product/review-delivery`"

If any gate fails, report the specific failures and suggest fixes.
