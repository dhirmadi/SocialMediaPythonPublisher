---
name: auth0-only-admin-review-traps
description: Review traps for #137 (Auth0-only admin) — load_dotenv defeats live 503 probes, tautological `or` asserts, template mutation dies on missing i18n key
metadata:
  type: project
---

Found reviewing PR #149 / issue #137 (password login removed, Auth0 is the only admin login).

- **A live `TestClient` probe of "no Auth0 configured" silently reads the developer's `.env`.**
  `web/service.py` calls `load_dotenv()` at import and `config/loader.py:470-472` calls it again on
  every `load_application_config`, with `override=False`. `os.environ.pop("AUTH0_DOMAIN")` is
  therefore undone and `is_admin_configured()` stays True, turning an expected 503 into a 403
  "Admin privileges required". Set the vars to `""` instead — `auth._get_env` treats blank as unset
  and dotenv will not overwrite a set-but-empty var. The pytest suite is immune: the root conftest
  rebinds `dotenv.load_dotenv` (and stale `from dotenv import load_dotenv` copies in every
  `publisher_v2.*` module) to a no-op unless an explicit path is passed.
- **`assert A or B or C` where C is a substring of the template is a dead assertion.**
  `assert '"auth_mode": "none"' in html or ... or "auth_mode" in html` can never fail: `auth_mode`
  appears ~7 times in `index.html`'s JS. The served value lives in `GET /api/config/features`, not
  in the page. Assert the endpoint's JSON value.
- **Reverting `index.html` alone kills a template test with `jinja2.UndefinedError`, not an
  assertion failure.** The i18n key set in `config/static/web_ui_text.en.yaml` moves with the
  template (`admin_dialog` removed). That still counts as a regression signal, but it is weaker
  than an assertion — restore both files if you want a clean mutation result.
- **`require_admin` is now unconditional on the image routes too** (`web/app.py` analyze/publish/
  keep/remove/delete) — this supersedes the note in [[docs-drift-review-traps]]. Bearer/Basic-only
  clients get 503 (no Auth0) or 403 (no cookie); `WEB_ALLOW_UNAUTHENTICATED=1` does not open them.
- **Cherry-pick verification trick that worked:** compare the two patches' `+`/`-` line multisets
  rather than file contents — `git diff -U0 <oldbase> <origcommit> -- f | grep '^[-+]' | sort` vs
  the same against the new base, then `comm`. Hunk offsets drop out and only genuine losses remain.

Related: [[mutation-check-review-technique]], [[test-isolation-review-traps]], [[web-template-test-traps]].

## Second pass (b12a702, 2026-09-20) — resolutions

- The dead `or "auth_mode" in html` assert is fixed: the test now asserts
  `client.get("/api/config/features").json()["auth_mode"] == "none"`. Mutation-confirmed red when
  `web/app.py:804` is forced to `auth_mode = "auth0"` (3 tests fail, incl. this one).
- `tests/conftest.py`'s `reset_web_rate_limiters` no longer touches `_consecutive_login_failures`;
  `test_test_isolation.py:86` now asserts `not hasattr(app_module, "_consecutive_login_failures")`
  as a tripwire. Mutation-confirmed red when the module global is reintroduced. Note the conftest's
  `if app_module is None: return` guard is now vestigial (the loop scans all `publisher_v2.web.*`),
  but harmless: every `SlidingWindowLimiter` instance lives in `web/app.py`.
- Still open (nit): `docs_v2/08_Epics/002_web_admin_curation_ux/020_auth0_login/020_design.md:45`
  lists `get_auth_mode()` with no `[removed #137: …]` annotation, though its neighbours on lines 38,
  46 and 47 got one and the function is gone from `web/auth.py` at the tip.
