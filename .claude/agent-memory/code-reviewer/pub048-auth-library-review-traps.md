---
name: pub048-auth-library-review-traps
description: PUB-048 review traps — require_admin strict mode must re-verify the header, guard-order inversion on voice-profile, per-key head_object fakes, AC2 params that pass pre-fix
metadata:
  type: project
---

PUB-048 (#187/#188) hardening left four things a future reviewer should re-check rather than re-derive.

**Why:** each is a place where a plausible-looking implementation or test silently proves nothing.

**How to apply:**
- `require_admin`'s strict-mode check (`web/auth.py`, after the `is_admin_request` check) must
  *re-verify* the `Authorization` header via `_verify_bearer`/`_verify_basic`. The naive
  `if is_auth_enabled() and _require_header_auth_with_cookie(): raise 401` regresses every route
  that calls `require_auth` then `require_admin` (valid header + valid cookie → 401). The positive
  parametrized test `test_require_admin_route_returns_200_under_strict_mode_with_valid_header_and_cookie`
  is the only guard for this.
- The voice-profile handlers call `require_admin(request)` **before** `await require_auth(request)` —
  owner-approved inversion of AC1's literal wording, recorded in the item's Change Log. The literal
  order breaks `test_password_login_removed.py::test_orchestrator_tenant_without_auth0_gets_403_with_valid_cookie`
  (503 instead of 403) and `test_admin_cookie_tenant_binding.py::test_cross_tenant_replay_returns_403_end_to_end`
  (401 instead of 403). Do not "fix" the order back.
- `tests/web/conftest.py::_FakeS3.head_object` is now **per-key** (raises `ClientError` code 404 for
  unknown keys) because upload does a pre-write existence check. This is faithful:
  `ManagedStorage.head_object` maps ClientError 404/NoSuchKey/NotFound to `None` and only warns on
  other codes. A fake that answers truthy for every key turns every first upload into a 409.
- In `test_require_admin_strict_mode.py` only 3 of the 12 parametrized call sites (`app.py:476`,
  `:859`, `:878`) actually fail against pre-fix code — the other 9 already 401 via `require_auth`.
  That is expected, not a weak test; the file's value is the uniform walk plus the positive case.
- AC11 (`_move_in_storage`'s 409 destination guard, `web/routers/library.py`) must sit **after**
  the AC6 `src_key == dst_key` 400 — otherwise a root→root self-move answers 409 and
  `test_move_target_root_when_already_in_root_rejects_same_key` (which asserts 400) fails. That
  existing test is the only thing pinning the order.
- `/api/library/objects/{f}/move` has **no UI consumer** (verified: `templates/index.html` curation
  buttons call `/api/images/{f}/keep|remove|delete`, not `/move`), which is why AC11 ships without
  an `overwrite` hatch. PUB-031's archived spec describes a "Move dropdown" that does not exist in
  the current template — do not take that doc as evidence of a consumer.
- The move-test `_FakeS3` has two seeds: `keys` (returned by the listing paginator, i.e. root) and
  `unlisted_keys` (head-only, e.g. `keep/`). Seeding a destination into `keys` is what makes the
  AC11 collision test real; a destination that is absent from both is what keeps every other move
  test at 200.
