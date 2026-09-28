# PUB-085: Gitleaks CI Honesty and Admin-UI Behaviour Coverage

| Field | Value |
|-------|-------|
| **ID** | PUB-085 |
| **Category** | Foundation |
| **Priority** | P2 |
| **Effort** | M |
| **Status** | In Progress |
| **Dependencies** | PUB-084 (done) |

## User Story

As the maintainer, I want CI to claim only the gates it actually runs, and the admin UI behaviours that lost their only test in PUB-084 wave 3 to be pinned in a real browser, so that neither a secret scan nor a UI regression can slip through unnoticed.

## Problem

- **#303:** the `gitleaks` pre-commit hook (pinned v8.22.1) runs `gitleaks git --pre-commit --staged`, so it scans only staged changes. The CI `pre-commit` job runs `pre-commit run --all-files` on a fresh checkout with nothing staged. Gitleaks therefore scans nothing in CI, yet the job's comment lists it among the hooks that "run nowhere else". Locally, on `git commit`, it works.
- **#305:** PUB-084 wave 3 replaced ~140 `index.html` source-grep tests with an element contract and browser flows. Behaviours that only a grep pinned, and that the spec'd flows don't cover, now have no test: back-to-grid page, page-size persistence and upload lock, 429 wait-and-retry, clearing completed queue entries, Escape/ARIA in multi-select, the leave-page guards while uploading, and (from review) the absent password prompt.

## Owner decisions

- 2026-09-28: address #303 and #305 after PUB-084. For #303 the implementer chose "local-only, stated honestly" over adding another secret scanner to CI: TruffleHog already scans every PR and main-push diff and the full history weekly (verified findings only), the GitGuardian GitHub App scans PRs (the "GitGuardian Security Checks" check; the ggshield step in `security-scan.yml` is skipped because the repo has no `GITGUARDIAN_API_KEY` secret), and detect-secrets scans all files. The owner may reverse this.

## Desired Outcome

CI no longer runs or claims a gitleaks gate it cannot enforce, and the docs say where gitleaks does run. Each #305 behaviour is either pinned by an e2e flow or recorded on #305 as intentionally dropped.

## Scope

**In scope:**
1. **#303:** the CI `pre-commit` job skips the `gitleaks` hook explicitly (`SKIP=gitleaks`), with a comment saying why; its "run nowhere else" comment no longer lists gitleaks; `SECURITY.md` states gitleaks is a local commit-time hook and lists the CI secret scanners. The hook stays in `.pre-commit-config.yaml`.
2. **#305:** Playwright flows in `publisher_v2/tests/e2e/` (same harness: real app on loopback, `FakeS3`, scripted OpenAI fake, minted admin cookie, no fixed sleeps) for:
   - back to grid opens the page holding the current image (GH-59), including the empty-page fallback;
   - page size is remembered across reloads (`localStorage`) and the page-size control is disabled while uploading;
   - a 429 on upload shows the waiting state and the upload is retried and completes;
   - enqueuing new files clears completed queue entries;
   - Escape leaves multi-select, and grid items expose `tabindex`, `role` and `aria-checked` in multi-select;
   - while an upload runs, leaving the page is guarded (`beforeunload`) and selecting a grid item asks for confirmation;
   - with `auth_mode` reported as `password`, the page never shows a password prompt.
   Any flow that exposes a real defect is fixed in `index.html` in the same PR.

**Out of scope:**
- A gitleaks CI scan of commit ranges or history (see Owner decisions).
- Template redesign.

## Acceptance Criteria

- AC1: Given `code-quality.yml`, when its `pre-commit` job is read, then the step running pre-commit sets `SKIP` to include `gitleaks`, and no comment in the file lists gitleaks as a hook enforced in CI
- AC2: Given `.pre-commit-config.yaml`, when it is read, then the `gitleaks` hook is still configured, and `SECURITY.md` names gitleaks as a local commit-time hook and names the scanners that run in CI
- AC3: Given each #305 behaviour, when the e2e suite runs, then a flow asserting it passes; a behaviour judged not worth pinning is listed on #305 with the reason
- AC4: Given the default `uv run pytest`, when it runs, then no e2e test is selected (unchanged)
- AC5: Given this item ships, when its PRs merge, then #303 and #305 are closed with `Closes #N`

## Related

- PUB-084 (#291 review), PUB-055 (CI security gates), PUB-078 (CI cleanup)
