---
name: secret-scan-docs-review-traps
description: PUB-085 part A - GitGuardian step skipped in every run (no repo secret); \bcommit regex matches pre-commit; SECURITY.md two-gates undercount
metadata:
  type: project
---

When a doc or spec cites GitGuardian (security-scan.yml) as a CI secret scanner, check it actually runs: GITGUARDIAN_API_KEY was not a repo secret on 2026-09-28 and the step concluded skipped (verify with gh run list --workflow security-scan.yml then gh run view ID --json jobs into a scratch file; the sandbox refuses jq -q filters inline).

**Why:** PUB-085 owner decision justified local-only gitleaks partly by "GitGuardian scans PRs", which was false in practice.

**How to apply:** doc-honesty tests using \bcommit or \blocal regexes over a paragraph pass on any paragraph containing "pre-commit"; mutate the claim to "enforced in CI" to prove it. SECURITY.md section 5 says "two blocking gates" while TruffleHog and detect-secrets also block. See [[ci-tooling-dedup-review-traps]] for the perl mutation recipe.
