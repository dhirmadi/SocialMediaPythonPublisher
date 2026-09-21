# PUB-048: Auth and Library Uniformity — Strict Mode, CSRF, OpenAPI, Self-Move, Non-Image Keys

| Field | Value |
|-------|-------|
| **ID** | PUB-048 |
| **Category** | Web UI |
| **Priority** | P0 |
| **Effort** | S |
| **Status** | Proposal |
| **Dependencies** | — |

## User Story

As an admin, I want every mutating route to enforce the same authentication and CSRF rules and every library operation to refuse a request that would destroy data, so that a stolen cookie or a stray API call cannot do what the UI would never do.

## Problem

The #75 and #128 hardening rounds landed the right checks but not uniformly (review [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177), security M1, M4, L1, L2, L3; all probed against the real app):

1. `POST` and `GET /api/config/voice-profile` (`web/app.py:853-878`) call `require_admin` only; every other mutating route calls `require_auth` first, and the `WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE` check lives only in `require_auth` (`web/auth.py:89-94`). With strict mode on, a cookie alone gets 401 on analyze and 200 on voice-profile, and the profile feeds the caption prompt.
2. `web/middleware_csrf.py:84` skips CSRF whenever an `Authorization` header is present, verified or not; `api_auth_logout` (`web/app.py:410`) has no auth dependency. A bogus Bearer plus a cookie logs the session out without `X-Requested-With`.
3. `web/app.py:193` keeps FastAPI's default `/docs`, `/redoc`, `/openapi.json`, exposing every route and the upload contract anonymously on every tenant host.
4. `web/routers/library.py:64` allows `target_folder="root"`, and `:490-505` always takes the source as `image_folder`, so `src_key == dst_key`; `ManagedStorage.move_object` (`managed_storage.py:697-710`) copies then deletes unconditionally. R2 and MinIO accept a same-key copy, so the object and its sidecar are deleted.
5. `_sanitize_filename("foo.txt")` passes (`library.py:208-230`); upload writes JPEG bytes under a sidecar name; delete has no listing check; upload silently overwrites an existing image.

## Desired Outcome

`require_admin` enforces strict mode itself, so no route can forget it. CSRF is bypassed only by a header that verifies. OpenAPI is not served anonymously. A move can never produce a same-key copy-then-delete. Upload and delete operate only on image keys the listing knows, and overwrite is explicit.

## Scope

**In scope:**
- Strict-mode check moved into `require_admin`
- CSRF bypass conditional on `_verify_bearer` or `_verify_basic` succeeding
- `docs_url=None, redoc_url=None, openapi_url=None`; optional admin-gated alternative
- Move: reject `src_key == dst_key` with 400; derive the source prefix from the object's actual folder
- Upload: allowed image suffix only (415 otherwise); 409 on an existing name unless `overwrite=true`
- Delete: image suffix required and `ensure_known_image` reused
- `.claude/rules/web-security.md` and the endpoint contract in `ARCHITECTURE.md` updated

**Out of scope:**
- Rate-limit keys (PUB-053)
- Key derivation (PUB-053)
- Any CSP change

## Acceptance Criteria

- AC1: Given `WEB_AUTH_TOKEN` is set and `WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE=1`, when a request with a valid admin cookie and no header hits `POST` or `GET /api/config/voice-profile`, then the response is 401 with the existing strict-mode message
- AC2: Given the app's route table, when every route that depends on `require_admin` is exercised under strict mode with a cookie only, then every one returns 401
- AC3: Given a cookie session and `Authorization: Bearer nope` with no `X-Requested-With`, when `POST /api/auth/logout` is called, then the response is 403 and the session is not revoked
- AC4: Given a valid Bearer token, when a mutating route is called without `X-Requested-With`, then CSRF is bypassed as today
- AC5: Given an anonymous request, when `/docs`, `/redoc` or `/openapi.json` is fetched, then the response is 404
- AC6: Given an object in the root folder, when `POST .../move` with `target_folder=root` is called, then the response is 400 and the fake storage received no copy and no delete
- AC7: Given an object in the keep folder, when it is moved to root, then the source key is the keep-folder key
- AC8: Given a multipart upload named `foo.txt` with valid JPEG bytes, when it is submitted, then the response is 415 and nothing is written
- AC9: Given an image `a.jpg` already exists, when `a.jpg` is uploaded without `overwrite=true`, then the response is 409; with `overwrite=true` the upload succeeds
- AC10: Given `DELETE /api/library/objects/foo.txt` or a name not in the listing, when it is called, then the response is 404 and nothing is deleted

## Implementation Notes

- Two sub-issues, two PRs: #187 (auth, CSRF, OpenAPI) and #188 (move, upload, delete).
- #187 touches `web.auth` internals; AGENTS.md gates that, so the PR body states the change and the owner's merge is the approval. `security-auditor` gate mandatory.
- The `overwrite` form field is a contract addition to the upload endpoint; default reject.

## Risks

- Moving the strict check into `require_admin` must not double-count a failed attempt in the login-attempt budget.
- Hiding OpenAPI may break an internal tool that reads it; check the Hetzner clone script before removing.

## Success Metrics

- A parametrised walk of every `require_admin` route returns 401 under strict mode with a cookie only.
- Zero `type: ignore` added; zero existing web tests changed in their assertions.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issues [#187](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/187), [#188](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/188)
- [PUB-020: Auth0 Login Migration](archive/PUB-020_auth0-login.md)
- [PUB-031: Managed Storage Migration & Admin Library](archive/PUB-031_managed-storage-migration-admin-library.md) — the library routes this hardens
- Prior fixes #91 (header auth with cookie), #137 (Auth0 only), #136 (upload gate)
