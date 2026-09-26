# PUB-065: Dependency Security Upgrades

| Field | Value |
|-------|-------|
| **ID** | PUB-065 |
| **Category** | Ops |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Implementation Complete |
| **Dependencies** | Blocks PUB-055 |

## User Story

As a maintainer, I want the locked dependencies free of known advisories, so that
PUB-055's blocking pip-audit gate can land green instead of red on a pre-existing
backlog.

## Problem

Making pip-audit genuinely blocking (PUB-055) revealed that `uv.lock` carried
98 advisories across 18 packages — including `authlib` and `cryptography`, both on
the Auth0 admin-cookie path. The 2026-09-21 hand review recorded these as current;
that check had gone stale, which is the decay PUB-055 exists to stop. PUB-055
cannot merge blocking-and-green until this is cleared, so this item goes first.

## Scope

**In scope:**
- Upgrade the packages carrying advisories, plus the minimum needed to resolve them
  (`fastapi` must move to reach `starlette` 1.x)
- Cap `instagrapi` below 3.0 and record why
- Resolve the one resulting test failure on its merits

**Out of scope:**
- Upgrading packages with no advisory. `uv lock --upgrade` also wanted
  `openai` 2.11→3.19, `sqlalchemy` 2.0→2.1, `uvicorn` 0.38→0.54, `rich` 14→15,
  `ruff` 0.15→0.16. None are advisory-driven, `openai` and `sqlalchemy` are majors
  on paths whose tests mock the external boundary, and `ruff` 0.16 reformats Python
  blocks inside Markdown (38 doc files). Left to Dependabot's weekly grouped PRs,
  which PUB-055 adds.
- `nltk` / `marshmallow`: reachable only through `safety`, which PUB-055 deletes.
  `nltk` has no fix for PYSEC-2026-3955 anyway, so upgrading it would not help.

## Acceptance Criteria

- AC1: Given the upgraded lock, when pip-audit audits the production dependency
  export, then it reports no known vulnerabilities. **Verified:** clean.
- AC2: Given the upgraded lock, when the full suite runs, then it passes.
  **Verified:** 1926 passed, 1 skipped.
- AC3: Given the upgraded lock, when format, lint and type checks run, then all
  pass. **Verified:** ruff format/check clean, mypy clean on 65 files.
- AC4: Given the prod+dev export, when pip-audit runs, then the only remaining
  advisories belong to `safety`'s tree. **Verified:** `nltk`, `marshmallow` only.

## Notes

### The one test that changed

`test_an_rfc2231_encoded_traversal_filename_is_sanitized_too` asserted that an
RFC 2231 `filename*=` traversal decoded to `evil.png` and was then sanitized to a
basename. `python-multipart` >= 0.0.27 ignores `filename*` outright — RFC 7578
section 4.2 forbids it in `multipart/form-data`, and it was removed as part of the
PYSEC-2026-3036/3037/3039/3040 header-parsing fixes this upgrade pulls in. The
hostile bytes now never reach `_sanitize_filename`, so the stored key is the
default `upload.jpg`.

A `security-auditor` pass traced the whole key-construction path and confirmed
this is strictly safer than before, that no other sink sees the raw filename, and
that the `upload.jpg` fallback cannot cause a silent overwrite (`_upload_to_storage`
409s unless `overwrite=true`, which is admin-only and rate-limited). The assertion
encoded a third-party parser's behavior rather than the security property the test
name states, so it was updated and negative assertions were added to pin the
property. The sibling plain-`filename=` traversal test is untouched and still green.

### Behavior change worth knowing

Uploads that supply a filename *only* via RFC 2231 now store as `upload.jpg`.
Browsers send UTF-8 in the plain `filename=` for form-data, and non-ASCII plain
filenames still round-trip, so this should not be visible in practice.

### Needs a manual pass before deploying

- `instagrapi` 2.2.1 → 2.18.20: session persistence and login flows are mocked in
  tests. Exercise a real login once.
- `cryptography` 46→50 and `authlib` 1.6.6→1.8.0 (now backed by `joserfc`) sit on
  the Auth0 ID-token verification path; the callback tests use stubbed tokens.
  Do one live Auth0 login.
- `starlette` 0.49→1.7 deprecates per-request `cookies=` in `TestClient`
  (83 warnings). Several auth tests assert 401/403 for a cookie-less request on a
  client that previously sent an admin cookie; if a future starlette persists
  per-request cookies into the jar, those negative assertions would stop guarding
  `require_admin`. Migrate those call sites before the kwarg is removed.

## Related

- Blocks PUB-055 (CI security gates)
