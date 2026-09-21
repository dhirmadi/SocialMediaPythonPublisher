---
name: csp-storage-origin-review-traps
description: Traps when reviewing web CSP/storage-origin, library move, and get_service-cache changes (#144 batch)
metadata:
  type: project
---

Verified facts from the #144 reviews that are expensive to re-derive.

**Why:** each cost a live experiment (worktree mutation runs, boto3 probe, Starlette probe).
**How to apply:** reuse instead of re-testing; re-verify only if the named file changed.

- `get_service` lru_cache is **load-bearing across test modules**. Removing the
  `with contextlib.suppress(Exception): get_service()` re-prime from the web fixtures makes
  all 6 tests in `publisher_v2/tests/web/test_web_settings_voice_profile.py` fail with
  `ConfigurationError: required env vars not set`. See [[runtime-settings-injection-traps]].
- `request.state` is backed by `scope["state"]` (starlette 0.49), so the **outermost**
  `SecurityHeadersMiddleware` reading state *after* `call_next` does see what `tenant_middleware`
  (registered first = innermost, `web/app.py:291` vs `:302`) attached.
- botocore 1.42 with a custom `endpoint_url` presigns **path-style**, so an origin derived from
  `endpoint_url` matches the presigned host.
- All `<img>` sources in `templates/index.html` are same-origin; only `handleFullSize`'s
  `fetch(currentFullUrl)` is cross-origin. A CSP storage origin is only needed in `connect-src`;
  `img-src` does not need it.
- `_move_in_storage` always uses `paths.image_folder` as the **source**, so moves are root-only.
- `WebImageService._get_cached_images` has a 30s TTL; #144 added `invalidate_image_listing()`
  called from library upload/move/delete only. Curation/publish archive paths still do not
  invalidate it.
- **`ManagedStorageConfig` does NOT validate `endpoint_url`.** Probed: `http://[evil`,
  `https://evil.example; script-src *`, `https://evil.example *`, `https://[2001:db8::1]:9000`
  and a tab-bearing host all construct fine. So validation must live in
  `middleware_security.storage_origins_for_config`, not the schema.
- `urlparse("http://[evil")` **raises** ValueError("Invalid IPv6 URL") — but in standalone mode
  the lifespan's blanket `except Exception` swallows it, so a standalone-only test can never
  prove the `try/except ValueError` inside `storage_origins_for_config`. Only the orchestrated
  `_storage_origins(request)` path (no outer guard) can 500. Mutation-test that branch by
  deleting the try/except and running `test_csp_storage_origin.py`: it stays GREEN.
- `urlparse` strips a tab from the netloc (`https://a\tb` -> netloc `ab`), so the tab param of
  `test_hostile_endpoint_cannot_inject_a_directive` is non-discriminating; only the `;` and
  space params fail under a permissive regex.
- Final #144 decision: bracketed IPv6 is **rejected** (`_SAFE_NETLOC_RE = [A-Za-z0-9.\-]+(:port)?`)
  because CSP host-source has no IPv6 production. PR #163's body still claims the opposite.
- Re-review of `f6befb3`: `storage_origins_for_config` is called **per request** from
  `SecurityHeadersMiddleware.dispatch` (`middleware_security.py:131`), so any WARNING added there
  fires on every request for a misconfigured tenant. Its `ValueError` branch (malformed endpoint,
  e.g. `http://[evil`) still returns early **without** logging, so the most likely typo is the one
  case with no operator signal.
- A comma **is** preserved by `urlparse` in the netloc, so `https://evil.example,other.example` is
  a discriminating hostile-endpoint param (unlike the tab).
- Re-review of `f3a8ec8` (dedup pass): the WARNING is now emitted from
  `@lru_cache(maxsize=128) _log_rejected_origin(scheme, fingerprint)`. Mutation-verified: dropping
  the decorator, dropping the unparseable-branch call, or re-adding `netloc_length` each reds
  exactly one test in `TestRejectedEndpointIsVisibleToOperators`. **But the `[:16]` scheme
  truncation has no test** — removing it leaves all 16 tests in `test_csp_storage_origin.py` green,
  and `urlparse('a'*5000+'x://host')` really does yield a 5001-char scheme, so the bound is load-
  bearing and unpinned.
- `log_json` runs `json.dumps`, and urlparse only fills `scheme` from `[A-Za-z0-9+.-]`, so a hostile
  endpoint cannot inject quotes/newlines into the log line — length was the only exposure.
- The rejected-origin WARNING carries **no tenant identifier** (scheme + 8-hex sha256 of the
  endpoint only). An operator cannot map the event back to a tenant from the log alone; this was
  equally true of the pre-`f3a8ec8` `netloc_length` form.
- Post-fix re-review of the whole `c3cc11d..a18acc2` range (2026-09-20): all 20 mutations I tried
  red the right test EXCEPT one. `test_library_move_sanitizing.py` **cannot detect the loss of
  `_sanitize_filename`** in `move_object`: replacing `safe_name = _sanitize_filename(filename)`
  with `safe_name = filename` leaves all 6 tests green. All three hostile params are absorbed by
  the `ensure_known_image` listing check (or by routing, for `..%2Fx.jpg`), and
  `assert response.status_code in (400, 404)` cannot tell the sanitizer's 400 from the listing
  check's 404. Fix: assert 400 exactly for `..%5Cx.jpg` and `%2e%2e.jpg`.
- Verified red: `[:16]` scheme truncation, the `@lru_cache` dedup, the unparseable-branch log,
  dropping `netloc_length`, the IPv6 rejection, a permissive netloc regex, the `try/except
  ValueError`, the restored `if history_dict:` guard, `history_size`, `generator = None`, the
  ASCII `_WORD_RE`, `re.match`, removing `ensure_known_image`, a no-op `_invalidate_listing`
  (and a rename of `invalidate_image_listing` is now a mypy error), the empty layering ALLOWLIST,
  and blanket `https:` back in the template.
- `_storage_origins` has a **second** fallback (`request.state.web_service.config`), so nulling
  only `request.state.config` does not prove the orchestrated end-to-end test works — both
  lookups must be disabled to red `TestOrchestratedRequestReachesTheHeader`.
