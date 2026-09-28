---
name: dead-file-guard-review-traps
description: PUB-084 wave 4 (#294/#286) - deleted-file guards checking disk not git index break the owner main checkout; un-ignoring local files; meter catch-all removal reasoning
metadata:
  type: project
---

Reviewed 2026-09-28 (uncommitted wave 4 on refactor/pub-084-dry-review-batch).

- **Deleted-file guards must check the git index, not Path.exists().** test_removed_scripts_are_not_referenced listed scripts/servers.txt, never tracked (gitignored) but present locally in the owner main checkout. A disk check passes in a fresh worktree/CI and fails on the owner machine after merge, where the pre-commit pytest hook then blocks commits. **Why:** worktrees hide local untracked/ignored files. **How to apply:** for ACs phrased "tracked files", use git ls-files; ls the main checkout for the named paths before signing off.
- The same diff removed the .gitignore line for that file so the reference scan would not flag .gitignore, which un-ignores a local ops file (git status shows ??). Exempt .gitignore from the scan instead.
- StorageOpsMeter _drain_loop catch-all removal is sound: _post_batch catches all but CancelledError, _drain_pending catches wait_for TimeoutError; only a log_json failure could escape, and asyncio would log "Task exception was never retrieved" at ERROR. The leftover "storage_ops_drain_task_failed" not-in assertion in the cancellation test became vacuous.
- Sandbox: scratch worktree + python -m pytest is refused; heredocs refused. For a HEAD coverage baseline: cp changed files to scratchpad, git checkout HEAD -- <files>, run, cp back, verify git diff --stat unchanged. Use printf to write memory files.

Related: [[e2e-playwright-review-traps]], [[mutation-check-review-technique]], [[reliability-batch-review-traps]].

Resolution (same day re-review): guard switched to the git ls-files set, .gitignore line restored and .gitignore exempted, historical exemptions narrowed to named files. Verified: full suite green with a local scripts/servers.txt present (and it shows as ignored); re-tracking a deleted script via git checkout HEAD -- <path> fails the guard (undo with git rm -q <path>).
