# Implementation Handoff: PUB-048 — Auth and Library Uniformity

**Hardened:** 2026-09-21
**Status:** Ready for implementation

This item is two independent sub-fixes with separate PRs (#187 auth/CSRF/OpenAPI, #188
move/upload/delete). Land #187 first: it changes `require_admin`'s contract (strict mode), and
#188's move fix doesn't depend on it, but #187 is the higher-severity fix (a stolen/leaked cookie
alone currently defeats strict mode entirely on two routes) and is a pure security tightening with
no new request fields, so it's lower-risk to land and verify independently first.

## For Claude Code

### Test-first targets

| AC | Sub-issue | Test file | Test name (exact function) |
|----|-----------|-----------|-----------------------------|
| AC1 | #187 | `publisher_v2/tests/web/test_web_settings_voice_profile.py` | `test_get_requires_admin_under_strict_mode_with_cookie_only` |
| AC1 | #187 | `publisher_v2/tests/web/test_web_settings_voice_profile.py` | `test_post_requires_admin_under_strict_mode_with_cookie_only` |
| AC2 | #187 | `publisher_v2/tests/web/test_require_admin_strict_mode.py` (new) | `test_require_admin_route_returns_401_under_strict_mode_with_cookie_only` (parametrized over every current `require_admin(` call site — see the AC2 text in the roadmap item for the exact list) |
| AC2 | #187 | `publisher_v2/tests/web/test_require_admin_strict_mode.py` (new) | `test_require_admin_route_returns_200_under_strict_mode_with_valid_header_and_cookie` (same parametrization; the positive case that catches the regression described in AC1's mechanism note — this is the test that would have failed against a naive "just check strict mode is configured" implementation) |
| AC3 | #187 | `publisher_v2/tests/web/test_csrf_middleware.py` (new) | `test_invalid_bearer_with_cookie_and_no_x_requested_with_is_blocked_and_session_not_revoked` |
| AC4 | #187 | `publisher_v2/tests/web/test_csrf_middleware.py` (new) | `test_valid_bearer_bypasses_csrf_without_x_requested_with` |
| AC5 | #187 | `publisher_v2/tests/web/test_web_hardening.py` | `test_docs_redoc_openapi_json_all_404_for_anonymous_request` (new `TestOpenApiDisabled` class) |
| AC6 | #188 | `publisher_v2/tests/web/test_library_move_sanitizing.py` | `test_move_target_root_when_already_in_root_rejects_same_key` |
| AC7 | #188 | `publisher_v2/tests/web/test_library_move_sanitizing.py` | `test_move_from_keep_folder_to_root_uses_keep_folder_as_source_key` |
| AC7 | #188 | `publisher_v2/tests/web/test_library_move_sanitizing.py` | `test_move_sidecar_txt_name_from_non_root_source_folder_returns_404` (negative case added in adversarial review — `ensure_known_object` must suffix-gate, not just check existence) |
| AC8 | #188 | `publisher_v2/tests/web/test_library_upload.py` | `test_upload_named_txt_with_valid_jpeg_bytes_returns_415` |
| AC9 | #188 | `publisher_v2/tests/web/test_library_upload.py` | `test_upload_existing_name_without_overwrite_query_param_returns_409` |
| AC9 | #188 | `publisher_v2/tests/web/test_library_upload.py` | `test_upload_existing_name_with_overwrite_query_param_true_succeeds` |
| AC10 | #188 | `publisher_v2/tests/web/test_library_delete_sanitizing.py` (new) | `test_delete_non_image_suffix_or_unlisted_name_returns_404_and_nothing_deleted` |
| AC11 | #188 | `publisher_v2/tests/web/test_library_move_sanitizing.py` | `test_move_onto_existing_destination_name_returns_409_and_nothing_copied_or_deleted` (added post-implementation — see the AC11 Change Log entry) |
| AC11 | #188 | `publisher_v2/tests/web/test_library_move_sanitizing.py` | `test_move_missing_object_from_non_root_source_folder_returns_404_and_nothing_copied_or_deleted` (covers `ensure_known_object`'s existence branch, dead-untested until the AC11 fake tightening) |

The **Test name** column is the exact `pytest` function name to create — the only spec-to-test
traceability link `/verify` and `/product-review-delivery` check against. If a name must change,
record the new mapping in the summary doc; don't silently rename.

### Mock boundaries

| External service / seam | Mock strategy | Existing fixture / pattern to reuse |
|---|---|---|
| Admin cookie (AC1, AC2, AC3, AC4) | `mint_admin_cookie_value(host="testserver")` set as the `pv2_admin` cookie on a real `TestClient`/`httpx.AsyncClient` against the real `publisher_v2.web.app.app` | `tests/web/test_web_settings_voice_profile.py::_admin`, `tests/web/test_web_hardening.py::client` |
| `WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE` strict mode (AC1, AC2) | `monkeypatch.setenv("WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE", "1")` plus `WEB_AUTH_TOKEN` set (strict mode is only meaningful when a header backend is configured) | new |
| `Authorization` header verification (AC3, AC4) | Real `_verify_bearer`/`_verify_basic` against a configured `WEB_AUTH_TOKEN`; no mocking needed — these are pure functions | `web/auth.py::_verify_bearer` |
| boto3 S3 client (AC6, AC7, AC8, AC9, AC10) | `unittest.mock.patch("publisher_v2.services.managed_storage.boto3")` + fake client recording `copy_object`/`delete_object`/`put_object` calls | `tests/web/test_library_move_sanitizing.py::_FakeS3`, `tests/web/conftest.py::_FakeS3`/`library_upload` |
| `WebImageService.ensure_known_image` / new `ensure_known_object` (AC7, AC10) | Real implementation against the fake S3's listing (`get_paginator(...).paginate(...)`) for root-scoped checks. For AC7's non-root source, `ensure_known_object` first suffix-gates the filename (same `_IMAGE_SUFFIXES` check as `ensure_known_image`) and only then calls `storage.head_object` — the positive test (`test_move_from_keep_folder_to_root_uses_keep_folder_as_source_key`) doesn't depend on `head_object` precision since the existing `_FakeS3.head_object` returns a fixed truthy dict regardless of `Key`; the negative test (`test_move_sidecar_txt_name_from_non_root_source_folder_returns_404`) is caught by the suffix gate *before* `head_object` is ever reached, so it needs no change to that fake either. If a future test needs a genuinely-missing (correct-suffix) object in a non-root folder, tighten `head_object` then to check `kwargs["Key"] in self.keys` (verify this doesn't affect any current move-sanitizing assertion — none of them call `head_object` today) | `tests/web/test_library_move_sanitizing.py` |
| Multipart upload body (AC8, AC9) | `library_upload` fixture (`_FakeS3`, `_UploadHarness`, `CountingUploadBody`) already in `tests/web/conftest.py` — reuse as-is; AC9's `overwrite` is a query string param (`library_upload.post(body, ...)` → extend `_UploadHarness.post` to accept an optional query string, or append `?overwrite=true` to the literal path in the new tests) | `tests/web/conftest.py::library_upload` |

### Files likely touched

| Area | Files to modify | Files to create |
|---|---|---|
| #187 auth/CSRF/OpenAPI | `publisher_v2/src/publisher_v2/web/auth.py` (`require_admin`), `publisher_v2/src/publisher_v2/web/app.py` (voice-profile handlers, `FastAPI(...)` constructor), `publisher_v2/src/publisher_v2/web/middleware_csrf.py`, `.claude/rules/web-security.md`, `docs_v2/03_Architecture/ARCHITECTURE.md` | `publisher_v2/tests/web/test_require_admin_strict_mode.py`, `publisher_v2/tests/web/test_csrf_middleware.py` |
| #188 move/upload/delete | `publisher_v2/src/publisher_v2/web/routers/library.py` (`LibraryMoveRequest`, `_move_in_storage`, `upload_file`, `_delete_from_storage`), `publisher_v2/src/publisher_v2/web/service.py` (new `ensure_known_object`) | `publisher_v2/tests/web/test_library_delete_sanitizing.py` |

### Non-negotiables for this item

- [ ] Preview mode: N/A — this item touches only the web admin API surface, never the CLI/preview
      path (`app.py`, `WorkflowOrchestrator`).
- [ ] Secrets: none introduced; no new credential or token handling. `overwrite` is a plain bool
      query param, not a secret.
- [ ] Auth: this item's entire purpose is auth/CSRF tightening. `require_admin`'s new strict-mode
      check must run *after* its existing `is_admin_request` check (403 for no/invalid cookie must
      win over 401 for missing header — see Implementation Notes in the roadmap item). Do not
      remove the existing strict-mode check inside `require_auth` (`web/auth.py:89-94`) — it stays,
      the new check in `require_admin` is additive so `require_admin`-only call sites are covered
      too. Do not add a password-login path back (#137 is final).
- [ ] Async hygiene: N/A — no new I/O paths; `ensure_known_object`'s `storage.head_object` call is
      already async in the `ObjectStorageProtocol`.
- [ ] Backward compatibility: `LibraryMoveRequest.source_folder` defaults to `"root"`, so every
      existing caller that only sends `target_folder` behaves exactly as before. `overwrite`
      defaults to `False` (existing upload behavior for a new name is unaffected; uploading an
      *existing* name without `overwrite=true` changes from a silent overwrite to a 409 — this is
      the intended AC9 fix, not a compatibility break to avoid). `/docs`/`/redoc`/`/openapi.json`
      going from 200 to 404 is the intended AC5 fix.
- [ ] Coverage: ≥80% on `web/auth.py`, `web/middleware_csrf.py`, `web/routers/library.py`,
      `web/service.py` (new method); ≥85% overall.

### Sequencing / dependency notes

- #187 and #188 touch disjoint files (`web/auth.py`, `web/app.py`, `web/middleware_csrf.py` vs.
  `web/routers/library.py`, `web/service.py`) — no merge conflict expected regardless of order, but
  land #187 first per the rationale above.
- Within #188, AC6/AC7 (move) and AC8/AC9 (upload) and AC10 (delete) touch non-overlapping
  functions in `library.py` (`_move_in_storage` vs. `upload_file`/`_upload_to_storage` vs.
  `_delete_from_storage`) — any order is fine.

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-048_auth-and-library-uniformity.md
```
