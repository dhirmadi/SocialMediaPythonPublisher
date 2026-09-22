# PUB-048 — Auth and Library Uniformity: Implementation Summary

**Status:** Implementation Complete
**Date:** 2026-09-21

Both sub-issues implemented in one working tree: #187 (auth / CSRF / OpenAPI, AC1–AC5) and
#188 (move / upload / delete, AC6–AC10). They touch disjoint source files and can still be split
into two PRs at commit time; #187 should land first per the handoff.

## Files Changed

### Source — #187
- `publisher_v2/src/publisher_v2/web/auth.py` — `require_admin` gained the strict-mode check, in its
  header **re-verifying** form (`_verify_bearer`/`_verify_basic`), placed after the existing
  `is_admin_request` 403 branch. `require_auth`'s own check (`:88-94`) is byte-for-byte unchanged.
- `publisher_v2/src/publisher_v2/web/app.py` — both voice-profile handlers now call `require_admin`
  and `require_auth` (see Deviation below); `FastAPI(..., docs_url=None, redoc_url=None, openapi_url=None)`.
- `publisher_v2/src/publisher_v2/web/middleware_csrf.py` — CSRF bypass now requires an
  `Authorization` header that actually verifies, not one that merely exists. `api_auth_logout`
  untouched, per AC3.

### Source — #188
- `publisher_v2/src/publisher_v2/web/routers/library.py` — `LibraryMoveRequest.source_folder`
  (default `"root"`); new `resolve_library_folder` helper so source and target resolve identically;
  `_move_in_storage` rejects `src_key == dst_key` with 400 before any copy or delete, and moves the
  `<stem>.txt` sidecar from the resolved *source* prefix; `upload_file` gained an `overwrite: bool = False`
  **query** param and a suffix gate placed before the Pillow decode; `_upload_to_storage` returns 409
  on an existing name without `overwrite`; `_delete_from_storage` starts with `ensure_known_image`.
- `publisher_v2/src/publisher_v2/web/service.py` — new `WebImageService.ensure_known_object(folder, filename)`,
  suffix-gating on `_IMAGE_SUFFIXES` **before** `head_object`. `ensure_known_image` unchanged.

### Tests
- `publisher_v2/tests/web/test_require_admin_strict_mode.py` (new) — AC2, parametrized over all 12
  `require_admin(` call sites, negative and positive.
- `publisher_v2/tests/web/test_csrf_middleware.py` (new) — AC3, AC4.
- `publisher_v2/tests/web/test_library_delete_sanitizing.py` (new) — AC10.
- `publisher_v2/tests/web/test_web_settings_voice_profile.py` — AC1 (`TestVoiceProfileStrictMode`).
- `publisher_v2/tests/web/test_web_hardening.py` — AC5 (`TestOpenApiDisabled`).
- `publisher_v2/tests/web/test_library_move_sanitizing.py` — AC6, AC7 (+ negative).
- `publisher_v2/tests/web/test_library_upload.py` — AC8, AC9 (`TestSuffixAndOverwrite`).
- `publisher_v2/tests/web/conftest.py` — `_UploadHarness.post(query=...)`; `_FakeS3.head_object` made
  per-key (see Test-double changes below).

### Docs
- `.claude/rules/web-security.md`, `docs_v2/03_Architecture/ARCHITECTURE.md` — strict mode is now
  enforced inside `require_admin` itself, including the read-only `app.py:476` view-permission call site.

## Acceptance Criteria

- [x] AC1 — strict mode enforced in `require_admin` (`test_get_requires_admin_under_strict_mode_with_cookie_only`, `test_post_requires_admin_under_strict_mode_with_cookie_only`)
- [x] AC2 — all 12 `require_admin` call sites 401 on cookie-only, 200 on valid header + cookie (`test_require_admin_route_returns_401_under_strict_mode_with_cookie_only`, `test_require_admin_route_returns_200_under_strict_mode_with_valid_header_and_cookie`)
- [x] AC3 — bogus Bearer no longer bypasses CSRF on logout (`test_invalid_bearer_with_cookie_and_no_x_requested_with_is_blocked_and_session_not_revoked`)
- [x] AC4 — valid Bearer still bypasses CSRF (`test_valid_bearer_bypasses_csrf_without_x_requested_with`)
- [x] AC5 — `/docs`, `/redoc`, `/openapi.json` all 404 (`test_docs_redoc_openapi_json_all_404_for_anonymous_request`)
- [x] AC6 — same-key move rejected with 400, no copy/delete (`test_move_target_root_when_already_in_root_rejects_same_key`)
- [x] AC7 — source prefix derived from `source_folder` (`test_move_from_keep_folder_to_root_uses_keep_folder_as_source_key`), sidecar `.txt` refused (`test_move_sidecar_txt_name_from_non_root_source_folder_returns_404`)
- [x] AC8 — non-image suffix upload → 415 (`test_upload_named_txt_with_valid_jpeg_bytes_returns_415`)
- [x] AC9 — existing name → 409 unless `?overwrite=true` (`test_upload_existing_name_without_overwrite_query_param_returns_409`, `test_upload_existing_name_with_overwrite_query_param_true_succeeds`)
- [x] AC10 — non-image or unlisted delete → 404, nothing deleted (`test_delete_non_image_suffix_or_unlisted_name_returns_404_and_nothing_deleted`)
- [x] AC11 — move onto an existing destination name → 409 before any copy or delete (`test_move_onto_existing_destination_name_returns_409_and_nothing_copied_or_deleted`). Added *after* the first implementation pass, from an adversarial audit of the finished branch.

Zero test-name drift: all 16 handoff test names match verbatim. The handoff table originally had 14 rows (AC1-AC10); the two AC11 rows were added to it when AC11 was, so the table and the tree agree.

## Test Results

```
uv run pytest -q --cov --cov-report=term-missing
1799 passed, 1 skipped, 83 warnings in 83.82s
```

(1797 at the first implementation pass; +2 from AC11.)

Re-run under other random seeds (e.g. `--randomly-seed=13579`): 1799 passed, 1 skipped. No isolation
defect from the new fixtures.

Mutation check (reviewer, detached worktree at HEAD with the new tests): 15 of 16 new test cases fail
against pre-fix source. The one that passes pre-fix is AC4's, which is by design a regression guard.

## Quality Gates

- Format: ✅ `ruff format --check .` → 244 files already formatted
- Lint: ✅ `ruff check .` → All checks passed
- Type check: ✅ `mypy publisher_v2/src --ignore-missing-imports` → no issues in 64 source files
- Tests: ✅ 1799 passed, 0 failed, 1 skipped
- Coverage: ✅ TOTAL 92.81% (gate 85). Per-module: `web/auth.py` 93%, `web/middleware_csrf.py` 90%,
  `web/routers/library.py` 96%, `web/service.py` 82% — all over the 80% bar.
- Success metrics: zero `type: ignore` added (`web/service.py` uses `cast(...)` instead); no existing
  test's assertions changed.

## Subagent Verdicts

- `code-reviewer`: **PASS WITH NITS** — zero spec-to-test drift, no "cannot fail" test, all four
  known-wrong mechanisms avoided; 4 non-blocking nits recorded below.
- `security-auditor` (pass 2, on the committed branch): **PASS WITH NITS** — raised the move destination-collision finding that became AC11.
- `security-auditor` (pass 3, verifying AC11): **PASS WITH NITS** — original finding **closed**, mutation-verified; guard prevents both the copy and the delete before any side effect.
- `code-reviewer` (pass 2, on the committed branch): **PASS WITH NITS** — independently re-ran all gates, mutation-checked the AC1 mechanism (naive form fails 12/12).
- `security-auditor` (pass 1): **PASS WITH NITS** — all five claimed holes genuinely closed, no new hole
  opened (no secrets, no logging leak, no auth bypass, no traversal, no blocking call on the loop,
  no `#137` password-login regression, preview safety untouched).

## Notes

### Deviation from AC1 (owner-approved during `/implement`)

AC1 directs `await require_auth(request)` to be added *before* `require_admin(request)` in the two
voice-profile handlers. Implemented literally, that ordering makes `require_auth` shadow
`require_admin`'s 403 on exactly those routes and breaks two previously-green tests'
assertions — `test_password_login_removed.py::test_orchestrator_tenant_without_auth0_gets_403_with_valid_cookie`
(503 instead of 403) and `test_admin_cookie_tenant_binding.py::test_cross_tenant_replay_returns_403_end_to_end`
(401 instead of 403) — contradicting this item's own Success Metric "zero existing web tests changed
in their assertions". The owner chose the inverted order: `require_admin(request)` then
`await require_auth(request)`. Both guards still run unconditionally (verified by the security
auditor), so the posture is identical; only which status wins on a double failure changes, and
403-beats-401 is the precedence the item's own Implementation Notes call for. No strict-mode coverage
is lost, because AC1's mechanism moves strict-mode enforcement inside `require_admin` itself.
Recorded in the roadmap item's Change Log.

### Test-double changes (reviewed, not assertion changes)

Two fakes' `head_object` were made per-key rather than unconditionally truthy, because AC9 adds a real
pre-write existence check and a blanket-truthy fake turns every *first* upload into a 409:
`tests/web/conftest.py::_FakeS3` and the new `test_require_admin_strict_mode.py::_FakeObjectStorage`.
The reviewer confirmed this is faithful to the real seam — `ManagedStorage.head_object` maps
`404/NoSuchKey/NotFound` to `None` — and verified against pre-change source that it hides no defect.

### AC11: a hole this item opened, found after it was "done"

The first implementation pass shipped AC1-AC10 with two clean review verdicts. A second adversarial
`security-auditor` pass on the *committed* branch then found that AC7's new `source_folder` had opened
a fresh data-loss path: `_move_in_storage` had no destination-collision guard, so moving `a.jpg` from
keep onto an existing `a.jpg` in root would copy over the destination and then delete the source,
destroying the root object and its sidecar. Before this item, the source was hardcoded to root, so
`X -> root` moves were unreachable and the collision could not occur. The asymmetry with AC9's
brand-new upload 409 is what surfaced it.

This is the failure class PUB-048 exists to prevent, introduced by PUB-048 itself. AC11 was added to
the spec, then implemented TDD-style: a failing test, then an 8-line guard raising 409 before any copy
or delete. The AC6 same-key 400 still wins over the 409, and that ordering is pinned by the existing
`test_move_target_root_when_already_in_root_rejects_same_key`.

**No `overwrite` escape hatch was added**, unlike AC9's upload. There is no UI consumer of `/move`
(verified by grep of `templates/`), replacing an object via move is not an established workflow, and an
admin who wants it can delete the destination first. The failure mode of no hatch is a 409 costing one
extra call; the failure mode of a hatch is the data loss this AC is about.

Two test-side consequences, both previously deferred and now closed:
- `test_library_move_sanitizing.py::_FakeS3.head_object` went from blanket-truthy to per-key. This was
  required (a truthy fake makes *every* move 409) and is the tightening the handoff's mock-boundary
  table explicitly deferred.
- That tightening made `WebImageService.ensure_known_object`'s existence branch (`service.py:648-649`)
  testable. A `code-reviewer` pass had flagged it as dead-untested — an inverted condition there passed
  the entire suite. Now covered by
  `test_move_missing_object_from_non_root_source_folder_returns_404_and_nothing_copied_or_deleted`,
  mutation-verified in both directions.

### Endpoint contract change (backward compatibility)

`POST /api/library/objects/{filename}/move` onto an existing destination name was a 200 with a silent
clobber; it is now a 409. Intended, and no UI consumer exists, but it is a contract change and belongs
in the PR body alongside the AC5 `/docs` 404 and the AC9 upload 409.

### Other decisions

- AC7 sidecar semantics were unspecified. Decision: for a non-root `source_folder`, the `<stem>.txt`
  sidecar is read from and deleted at the **same** source prefix as the image.
- AC5's "optional admin-gated alternative" to OpenAPI was **not** implemented. No in-repo consumer of
  `/openapi.json` was found, and the spec says to skip it absent a concrete consumer.
- AC9's `overwrite` truthiness beyond `true` is unpinned; FastAPI's `bool` coercion also accepts `1`/`yes`.

### Carry into the PR body

1. **`app.py:476` behavior change** (spec requires this callout): the read-only image-view permission
   check is a `require_admin`-only call site like voice-profile was, so its behavior under strict mode
   changes too.
2. **OpenAPI consumer risk unconfirmed, not cleared**: no `/openapi.json` consumer exists in this repo,
   but one could exist outside it (e.g. `platform-orchestrator`). Flagged, not assumed clear.
3. **AC9 overwrite guard fails open on a transient storage error** (security-auditor finding 1):
   `ManagedStorage.head_object` returns `None` for *any* `ClientError`, not just 404, so a transient
   403/503 makes an existing image look absent and `overwrite=false` silently overwrites. Same class as
   the TOCTOU race the spec already accepts, and strictly better than today's unconditional overwrite.
   Worth a follow-up that distinguishes "absent" from "could not tell".
4. **`web.auth` internals changed** — AGENTS.md gates this; the owner's merge is the approval.

### Non-blocking nits recorded for follow-up (not fixed here — out of AC scope)

- `library.py:468` — the 409 detail advises `?overwrite=true`, but the UI's XHR error path renders
  `err.detail` verbatim and `uploadSingleFile` has no overwrite affordance to act on it.
- `library.py:527` — `resolve_library_folder(paths, source_folder)` sits outside the `try/except` that
  re-labels the target error, so a *direct* (non-router) call with a bad `source_folder` reports
  `"Invalid folder: X"`. Unreachable over HTTP; the route validates first.
- `library.py:465` — every upload now costs one extra billed `HEAD` through `StorageOpsMeter`.
- `library.py:846-852` — `_check_delete_rate_limit` still runs before `ensure_known_image`, so 404s for
  unknown names consume the delete budget. Pre-existing ordering, not introduced here.
- `library.py:825` — suffix gate and magic-byte check are independent, so `foo.png` carrying JPEG bytes
  is stored under a `.png` key with `content_type="image/jpeg"`. Metadata inconsistency, not a hole.
- `middleware_csrf.py:30` — cross-module private import of `_verify_bearer`/`_verify_basic`. Named
  explicitly by AC3; no import cycle, no semantic divergence (it calls the same functions the auth
  layer does, which is safer than a reimplementation).
