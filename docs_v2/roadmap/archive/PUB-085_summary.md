# PUB-085 — Gitleaks CI Honesty and Admin-UI Behaviour Coverage: Implementation Summary

**Status:** Implementation Complete (parts A and B)
**Date:** 2026-09-28

## Part A — Gitleaks CI honesty (#303)

### Files Changed

- `.github/workflows/code-quality.yml` — the `pre-commit` job's "Run every pre-commit hook" step sets `env: SKIP: gitleaks`, with a comment saying why: the pinned hook (`gitleaks git --pre-commit --staged`) diffs the index against HEAD, and a fresh CI checkout's index equals HEAD, so it could never fail in CI. The job header no longer lists gitleaks among hooks that "run nowhere else", and its false claim that `security-scan.yml` runs bandit with `|| true` is gone (no workflow runs bandit).
- `SECURITY.md` — "Security Scanning" now names three blocking gates. The secret-scanning bullet says gitleaks is a local hook on `git commit` that CI skips; that TruffleHog scans every PR and every push to `main`, plus a weekly or manual full-history scan reporting verified findings only; that detect-secrets scans all files in the `pre-commit` job; and that the GitGuardian GitHub App scans PRs, while the `ggshield` step in `security-scan.yml` is skipped because the repo has no `GITGUARDIAN_API_KEY` secret.
- `publisher_v2/tests/test_ci_security_gates.py` — AC1 and AC2 tests.
- `docs_v2/roadmap/PUB-078_*` — its stale "gitleaks actually blocks" claim corrected; Change Log line added.

### Acceptance Criteria

- [x] AC1 — the CI job skips gitleaks and says why; no comment claims CI enforces it (test: `test_ci_precommit_job_skips_gitleaks_and_says_why`)
- [x] AC2 — the hook stays configured; SECURITY.md describes gitleaks as a local `git commit` hook and names the CI scanners (test: `test_gitleaks_is_documented_as_a_local_hook`). It checks individual sentences: "pre-commit" does not satisfy "commit", and any sentence claiming CI enforcement fails unless it says the hook is skipped.

### Verification

- Mutations: removing `SKIP`, restoring the old "Four of its hooks … gitleaks … nowhere else" comment, re-adding gitleaks to the list, removing the why-comment, `SKIP: gitleaks-docker`, dropping TruffleHog from SECURITY.md, and SECURITY.md sentences calling gitleaks a CI gate (including "local hook and a blocking CI gate") all fail.
- `SKIP=gitleaks` skips only that hook id; detect-secrets, bandit, pydocstyle and ruff still run.
- actionlint clean; 12 tests in the file pass; default suite green.

### Subagent Verdicts

- `code-reviewer`: PASS WITH NITS. Applied: the vacuous "commit" match in AC2 tightened; GitGuardian's real state described (App on PRs, workflow step skipped); "two blocking gates" corrected; TruffleHog's push trigger limited to `main`; PUB-078's stale claim fixed.
- `security-auditor`: PASS WITH NITS. From the gitleaks v8.22.1 source, the CI run scanned nothing, so skipping it loses no coverage. Wording nits applied.

### Linked Issues

- #303 — closed by the part A PR (#313)

## Part B — Admin-UI behaviour coverage (#305)

Test-only; `index.html` unchanged. All ten behaviours passed on the current page, so no defect was found.

### Files Changed

- `publisher_v2/tests/e2e/test_ui_behaviours.py` — new: ten Playwright flows against the real app (loopback, `FakeS3`, scripted OpenAI fake, minted admin cookie, no fixed sleeps).
- `publisher_v2/tests/e2e/conftest.py` — `open_admin_page` (reusable, with a dialog policy), and `record_requests`, `open_grid` and `held_uploads` moved here from the test files so each exists once.
- `publisher_v2/tests/e2e/test_admin_flows.py` — uses the shared helpers; every assertion unchanged.

### Acceptance Criteria

- [x] AC3 — each #305 behaviour pinned (tests: `test_back_to_grid_opens_the_page_holding_the_current_image`, `test_back_to_grid_falls_back_when_the_page_is_empty`, `test_page_size_is_remembered_across_reloads`, `test_page_size_control_is_locked_while_uploading`, `test_rate_limited_upload_waits_and_retries`, `test_enqueuing_clears_finished_queue_entries`, `test_escape_leaves_multi_select_and_items_expose_aria`, `test_leaving_the_page_while_uploading_is_guarded`, `test_selecting_a_grid_item_while_uploading_asks_first`, `test_password_auth_mode_never_shows_a_password_prompt`). None dropped.
- [x] AC4 — the default run still deselects `e2e` (test: `test_default_run_deselects_e2e`).

### Notes

- Two flows shape one response in the browser with `page.route`, as their docstrings say. The 429: the real limiter's 60 s window is longer than the client's 5 s backoff, so every retry would get another 429; only the first upload is answered in the browser, and the retry reaches the real app. The `password` auth mode: the app only reports `auth0` or `none`, so only that field of the real response is rewritten.
- Enqueuing new files originally kept failed entries (pinned in part B). The owner ruled that a defect on 2026-09-28 (AC6): enqueuing now clears every finished entry, failed as well as completed, and keeps entries still in flight.
- The password flow detects a navigating hidden button in under a second: it records navigations and uses a same-page fetch as a barrier, instead of racing the URL.

### Test Results

`-m e2e`: 21 passed, stable over repeated fixed-order and random-order runs. Default suite: 2089 passed, 21 deselected. 22 template mutants, each built to break one flow's behaviour, all failed.

### Subagent Verdicts

- `code-reviewer`: PASS WITH NITS. Names match the handoff, there are no sleeps, both `page.route` uses are justified, and the `test_admin_flows.py` refactor is a pure extraction. The nit, a hidden-button navigation surfacing only as a 30 s timeout, is fixed. `security-auditor` was not needed: the change is tests only.

### Linked Issues

- #305 — closed by the part B PR (#314)

## Upload queue fix (AC6, owner decision 2026-09-28)

Part B pinned that failed upload entries survived when new files were enqueued; the owner ruled that a defect. Fixing it exposed that the queue also dropped uploads in several concurrent cases, each now pinned by a test that failed on the old page.

### Files Changed

- `publisher_v2/src/publisher_v2/web/templates/index.html`:
  - `enqueueFiles` validates first. A pick the client rejects entirely changes nothing. Otherwise it cancels any pending auto-hide, removes finished (done or failed) entries in place, and appends the new batch. It keeps anything still queued, uploading or waiting to retry, and keeps the array object a running loop holds.
  - `processUploadQueue` re-reads the queue until nothing is queued. `for...of` skipped a file once entries were removed in place.
  - The auto-hide timer is armed only when the batch was clean and no other loop is running, and only through `scheduleUploadAutoHide()`. It is cancelled only through `cancelUploadAutoHide()`, so at most one auto-hide is ever pending.
  - The callback's guard is kept as defence in depth and documented as unable to fire.
  - `dismissUploadQueue` no longer reassigns the array.
- `publisher_v2/tests/e2e/test_ui_behaviours.py`: the old queue test is renamed and re-expected as a spec change, and six AC6 flows exist in total.

### Acceptance Criteria

- [x] AC6 is covered by these tests:
  - `test_enqueuing_clears_finished_queue_entries`
  - `test_enqueuing_mid_upload_keeps_in_flight_entries`
  - `test_enqueuing_mid_upload_after_a_failure_sends_every_file`
  - `test_auto_hide_never_drops_a_batch_enqueued_after_a_clean_one`
  - `test_auto_hide_never_drops_a_batch_picked_during_the_grid_refresh`
  - `test_auto_hide_never_drops_a_batch_after_two_overlapping_clean_ones`
  - `test_picking_only_rejected_files_leaves_the_queue_untouched`

### Defects found along the way (all on `main` before this change)

- Picking files mid-upload kept only failed entries, so the in-flight upload vanished from the queue.
- Removing an earlier entry during a run made the loop skip a later file, which was never sent.
- A clean batch's 5 s auto-hide could empty the queue under a second batch and stop it.
- A timer armed by a loop still in its grid refresh, or orphaned by two overlapping clean batches, could later hide a failed entry and its Retry button.
- A pick of only rejected files left stale rows with dead Retry buttons.

### Verification

- The seven AC6 tests pass across many random-order runs. The full e2e suite (27) and the default suite (2089) pass.
- Each fix step has a template mutant that fails the test it targets. All AC6 tests fail on the `main` template.

### Subagent Verdicts

- `code-reviewer`: BLOCKED twice, then PASS. B1 was the grid-refresh arming race and B2 the orphaned timer; the reviewer found both by probe. W2 was the rejected-only pick. The fixes and tests above resolve them. The reviewer also re-ran the mirror order of B2.
- `security-auditor`: not run. The change is client-side queue logic with no auth or CSRF change; the XHR `X-Requested-With` header is unchanged.
