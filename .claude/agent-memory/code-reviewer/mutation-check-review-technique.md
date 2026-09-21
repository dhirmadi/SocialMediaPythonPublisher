---
name: mutation-check-review-technique
description: How to prove a new test can actually fail — detached worktree + targeted source mutations; the traps this catches in this repo
metadata:
  type: feedback
---

When a PR claims "each test goes red without its fix", verify it by mutation rather than by
reading the test.

**Why:** #144/PR #163 shipped two tests that could never fail for the fix they named, and a
conflict-marker block that sat dead inside a docstring while ruff and the whole suite reported
green. Reading the assertions did not reveal either; mutating the source did.
**How to apply:** for each fix commit, revert only its *source* hunk and run only its test file.

Recipe (read-only w.r.t. the working tree):
```
git worktree add --detach <scratch>/wt <branch>
ln -s <repo>/.venv <scratch>/wt/.venv          # reuse the venv, do not uv sync
cd <scratch>/wt
# mutate, then:
WEB_SESSION_SECRET=x <repo>/.venv/bin/python -m pytest -q -p no:cacheprovider -p no:randomly <file>
git checkout -- publisher_v2/src               # reset between mutations
git worktree remove --force <scratch>/wt       # always clean up
```
`git worktree add <path> <branch>` fails if the branch is checked out in the main worktree —
use `--detach`.

Recurring classes of "test that cannot fail" found in this repo:
- The test calls the **private helper** directly (`AIService._apply_similarity_gate`) while the
  fix was removing a guard in the **caller** (`generate_captions`). Restoring the guard leaves
  the test green.
- The failure the test names is swallowed by an outer blanket `except Exception` on the only
  code path the test exercises (standalone lifespan vs per-tenant middleware).
- A parametrized hostile input that the stdlib normalizes before it reaches the code under test.
- Assertions orphaned inside a string literal by a bad conflict resolution.

Also worth grepping history, not just the tip:
`for c in $(git rev-list base..head); do git grep -c -E '^(<<<<<<< |=======$)' $c -- '*.py'; done`
