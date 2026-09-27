# PUB-059: Web App Factory, Routers and Typed Platform Captions

| Field | Value |
|-------|-------|
| **ID** | PUB-059 |
| **Category** | Web UI |
| **Priority** | P2 |
| **Effort** | M |
| **Status** | Proposal |
| **Dependencies** | PUB-057, PUB-058 |

## User Story

As a platform maintainer, I want the web app built by a factory with its routes in routers and its per-platform captions carried by a real type, so that two apps can exist in one process for testing, a new route cannot forget a dependency, and adding a platform touches an enum and a YAML entry rather than eight files.

## Problem

Review [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177), architecture A5 to A7; sub-issues [#209](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/209) (factory and routers) and [#210](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/210) (types). Line numbers below are from the 2026-09-27 audit at `main` 949b2d1 unless marked as from the issue.

**Web app (#209):**

- `web/app.py` defines 20 route handlers (#209 counted 17 before the voice-profile routes at `:864` and `:888` were added): index, three health (`/health/live`, `/health/ready`, `/health`), admin status, two logout routes (`/api/auth/logout`, `/api/admin/logout`), nine image routes (list, random, get, analyze, publish, keep, remove, delete, thumbnail) and four config routes (publishers, features, voice-profile GET and POST). `web/routers/` holds only `auth.py` and `library.py`. The image routes are the core admin API. There is no `create_app`.
- Module-level mutable globals in `src` (complete list, file:line from #209): `web/app.py:74-76` three `SlidingWindowLimiter`s; `web/app.py` `templates`; `web/app.py:310` `session_secret = os.environ.get(...)`, an import-time env read that raises without a secret (`conftest.py:29` must `setdefault` it before any import); `web/auth.py:156` `_REVOKED_SIDS`; `web/service.py:138` `_PUBLISH_LOCKS`; `web/routers/library.py:124-125` two rate dicts; `web/routers/auth.py:25` `oauth`; `services/_http.py:18-19` shared client and lock; `db/__init__.py:18-22` engine, session factory and health cache; `config/loader.py:56` once-flag; plus two `lru_cache` singletons (`config/source.get_config_source`, `web/dependencies.get_service`, still at `web/dependencies.py:16`). `conftest.py:117-206` needs three autouse fixtures to reset them.
- Three wiring styles: `Depends(get_request_service)` reads `request.state.web_service` set by `tenant_middleware`, else falls back to the `lru_cache` singleton (`dependencies.py:16-33`); runtime settings via `app.state` with an env-reparse fallback (`web/settings.py:27-52`); auth via direct env reads inside `require_admin`; CSP origins from `app.state.csp_storage_origins` in standalone but `request.state.config` in orchestrated mode (`middleware_security.py:148-152`). The lifespan builds the standalone singleton on every boot and swallows the failure "by design" in orchestrated deployments (`app.py:128-140`, from #209).

**Types (#210):**

- `dict[str, str]` for captions in eleven signatures (from #210): `services/ai.py:1177, 1569`; `services/sidecar.py:42, 133`; `web/service.py:721`; `web/models.py:61, 81`; `core/workflow.py:505, 780`; `core/models.py:176` (`platform_captions: dict[str, str]`, confirmed at 949b2d1); `utils/preview.py:164`. `dict[str, str]` appears 65 times in `src` overall. No `Platform` or `PlatformCaptions` type exists; platform names are bare strings compared in five or more modules.
- `CaptionSpec.for_platforms` (`core/models.py:73`) hard-codes the telegram, instagram and email enabled flags. Adding a platform touches the domain model, `PlatformsConfig`, the loader, two YAMLs, static defaults, `_MAX_LEN` and the template.
- `dict[str, Any]` appears 92 times in `src` (84 when #210 was filed). The sidecar view travels as `dict[str, Any]` (`web/service.py:71, 702`, from #210); `metadata: dict[str, Any] | None` on `ImageResponse` (`web/models.py:35`). The writer builds text (`utils/captions.py:250` `build_caption_sidecar`) and the reader re-parses it defensively (`services/sidecar_parser.py:64, 163`, including `_recover_python_repr_mapping:41` for a past bug); `web/sidecar_parser.py` is a 10-line re-export shim. PUB-051 added the per-platform `caption_angles` sidecar key alongside `caption_generated` and `caption_submitted`, read back as untyped dicts in `core/workflow.py` (`:1234-1273`).
- `json.loads` at 11 sites; `services/ai.py:489, 1076, 1347, 1399` (from #210) each parse model output with their own error handling.
- `web/app.py:920` mutates `service.config.content.voice_profile` in place (`:891` when #210 was filed); `ApplicationConfig` is neither frozen nor request-scoped.
- Ten `getattr(config.x, "field", default)` sites exist because fixtures pass `SimpleNamespace` stand-ins (`conftest.py:308-345` `minimal_app_config`); the test doubles shape the domain code.
- `web/models.py:93` `PublishResponse.results: dict[str, dict[str, Any]]` instead of `PublishResult`; `AnalysisResponse` (`:43-66`) re-lists `ImageAnalysis` fields by hand.

## Desired Outcome

`create_app(settings) -> FastAPI` with limiters, revocation set, templates, secret, oauth registry and publish locks as instance state; `routers/images.py` and `routers/config.py`; one service dependency; one CSP origin source. A `Platform` StrEnum and `PlatformCaptions` used end to end; a `SidecarDocument` model shared by writer and parser; a frozen `ApplicationConfig` with request-scoped overrides; fixtures that build real config objects; response models derived from domain types.

## Scope

**In scope:**
- App factory `create_app(settings: RuntimeSettings) -> FastAPI`; module `app` kept importable for uvicorn (Procfile unchanged unless the owner approves a factory target)
- Limiters, revocation set, templates, session secret, oauth registry and publish locks become `app.state` instance state; no import-time env read left in `web/`
- Image routes moved to `routers/images.py`, config routes (including voice-profile) to `routers/config.py`; `app.py` keeps index, health, admin status and logout
- One service dependency `get_request_service`; `web/dependencies.get_service` deleted; CSP origins read from one place in both modes
- conftest autouse resets reduced to those still needed (db engine)
- `Platform` StrEnum in `core/models.py`; `PlatformCaptions = Mapping[Platform, str]` used end to end; `CaptionSpec.for_platforms(enabled: Iterable[Platform], styles)` without a hard-coded list
- `SidecarDocument` pydantic model used by both writer and parser, covering every current sidecar key including `caption_generated`, `caption_submitted` and `caption_angles` (PUB-051); repr-recovery deleted once a migration test shows no legacy sidecars remain in the fixtures, kept behind a flag otherwise
- One `parse_model_json(text, expected_keys)` helper for the four `ai.py` parse sites
- Frozen `ApplicationConfig`; voice-profile override as request-scoped service state, not a config mutation
- Fixtures build real config objects; the ten `getattr` defaults deleted
- `PublishResponse.results: dict[Platform, PublishResult]`; `AnalysisResponse` derived from `ImageAnalysis`
- Ratchets on module-level globals and `dict[str, Any]` occurrences in `src`, each may only fall

**In scope (absorbed 2026-09-27 from the DRY review, [#291](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/291)):**
- Routes ([#276](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/276)): a `require_admin_action` dependency for the admin image routes (voice-profile keeps its own guard order — the order decides 401 vs 403; no auth weakening, see `.claude/rules/web-security.md`); a router-level dependency on `library.router` covering auth, `_check_library_available` and a typed storage accessor; one `run_service(event, ...)` helper for the telemetry/`raise_for_service_error` block, with the thumbnail's `DecompressionBombError` moved into `raise_for_service_error`; one curation route handler and one `WebImageService._curate(filename, action)`, the curation feature flag checked once, and the orchestrator's always-`False` `preview_mode`/`dry_run` curation parameters removed
- Dead web surface ([#279](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/279)): the OpenAPI-only `responses=`/`deprecated=`/`_UPLOAD_REQUEST_BODY` metadata (the schema is not served); `POST /api/admin/logout` (app.py keeps one logout) and `GET /health` once no external probe uses it; the Auth0 router's dead branches (`ensure_oauth_configured` returns the config, one `_auth_error(code)`, the unused `redirect_uri` block); the `mode=` parameter on admin-cookie mint/set left from #137 (read-side check kept); unused middleware knobs `csp_template`, `api_prefix`, `trust_forwarded_headers`
- Publisher template ([#278](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/278)): `Publisher.publish()` in `publishers/base.py` does the enabled check, timing and sanitised failure logging around an abstract `_publish(...) -> post_id`; `platform_name` becomes a class attribute; the email subject/body becomes one `email_subject(config, caption)` computed before connecting. This is what makes AC4's "one publisher" true for PUB-027/PUB-030
- Service construction ([#285](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/285)): one `_resolve_secret(ref_key, model, field)` for AI/email/telegram; one `AIService.from_openai_config(...)`; the orchestrator built only lazily, so standalone gets the meters too; the redundant lazy lock and local re-imports go; `_publish_lock` becomes a plain per-app dict if #181 says `DATABASE_URL` is always provisioned
- CLI preview ([#282](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/282)): `build_sidecar_metadata`, `sidecar_model_version`, `utc_now_iso_z` (on `SidecarDocument`) used by both the writer and `app.py`'s preview; the preview's email subject from `email_subject`; preview widths from static config; `generate_and_upload_sidecar`'s unused `caption_generated`/`caption_edited` keyword parameters and wrong docstring, `print_curation_action`, the `is_new` parameter and `print_vision_analysis`'s `getattr` probes deleted

**Out of scope:**
- New platforms themselves (PUB-027, PUB-030 become one-enum-entry items after this)
- Template redesign

## Acceptance Criteria

- AC1: Given two apps created with different settings in one process, when each is driven, then limiter and revocation state are not shared
- AC2: Given `WEB_SESSION_SECRET` is unset, when `publisher_v2.web.app` is imported, then no exception is raised; when `create_app` is called, then it raises naming the variable
- AC3: Given `web/app.py`, when its routes are listed, then no image or config route is defined there
- AC4: Given the enum gains a fourth platform and the YAML an entry, when `for_platforms` and the sidecar round-trip run parametrised over the enum, then no other change is needed beyond the enum, one YAML entry and one publisher
- AC5: Given every field type the sidecar supports (including `caption_generated`, `caption_submitted` and `caption_angles`), when the writer output is parsed, then the round-trip is identity; given legacy fixtures, then they still parse
- AC6: Given `src`, when it is searched, then no `getattr(..., "field", default)` on a config object and no `dict[str, str]` caption signature remains
- AC7: Given the ratchets, when each PR merges, then the module-level global count and the `dict[str, Any]` count are not higher than before
- AC8: Given `web/`, when it is searched, then no module-level (import-time) env read remains
- AC9: Given the web package, when service and CSP wiring are inspected, then exactly one service dependency (`get_request_service`) exists, `get_service` is gone, and CSP origins come from one source in standalone and orchestrated mode
- AC10: Given the sidecar writer and parser, when their code is inspected, then both use the one `SidecarDocument` model
- AC11: Given `conftest.py`, when its autouse fixtures are listed, then only the resets still needed (db engine) remain
- AC12: Given every admin and library route, when the existing auth tests run unedited, then each returns the same 401/403/404/503 as before; one curation handler serves keep, remove and delete
- AC13: Given the web package, when it is searched, then no `responses=` OpenAPI metadata, no `/api/admin/logout` route and no cookie `mode=` write parameter remain; the PR is audited by the security-auditor subagent
- AC14: Given each publisher, when its class is inspected, then it implements only `_publish` and failure results and logs are unchanged
- AC15: Given standalone mode, when the orchestrator is built, then it is built once, lazily, with the usage and storage-ops meters attached
- AC16: Given one fixture image, when `--preview` and the real writer run, then the sidecar metadata is identical and the preview's email subject equals `EmailPublisher`'s
- AC17: Given this item ships, when its implementing PRs merge, then [#276](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/276), [#278](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/278), [#279](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/279), [#282](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/282) and [#285](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/285) are closed with `Closes #N` in the PR body

## Implementation Notes

- Two sub-issues: #209 (factory and routers), #210 (types). After PUB-057 step 4 (settings injection) and PUB-058.
- A Procfile change to a factory target is an ask-first item; prefer `app = create_app(load_runtime_settings())` at module bottom guarded so import stays side-effect free.
- Test first (from the sub-issues):
  - `tests/web/test_app_factory.py` (new): AC1 and AC2.
  - `tests/test_module_globals.py` (new ratchet): count of module-level mutable globals in `src`, may only fall.
  - `tests/test_platform_types.py` (new): AC4, parametrised over the enum.
  - `tests/test_sidecar_schema.py` (new): AC5.
  - A ratchet on `dict[str, Any]` occurrences in `src`, may only fall.
  - Existing web tests keep their assertions; only fixture wiring changes to the factory.
- Verification:

```bash
uv run ruff format --check . && uv run ruff check .
uv run mypy publisher_v2/src --ignore-missing-imports
WEB_SESSION_SECRET=x uv run pytest -q -p no:cacheprovider publisher_v2/tests/web
WEB_SESSION_SECRET=x uv run pytest -q -p no:cacheprovider -k "platform_types or sidecar or caption_spec"
WEB_SESSION_SECRET=x uv run pytest -q -p no:cacheprovider
```

## Risks

- The template's JavaScript calls routes by path; moving routes must keep every path identical (assert with a route-table snapshot test).
- Freezing `ApplicationConfig` breaks any test that mutates it; those tests are the ones this item wants to find.

## Success Metrics

- conftest autouse fixtures down from three to one.
- PUB-027 and PUB-030 re-scoped to S after this lands.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issues [#209](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/209) and [#210](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/210), folded into this item on 2026-09-27 (the spec is now the tracking record for both)
- [PUB-027: Bluesky Publisher](PUB-027_bluesky-publisher.md), [PUB-030: Mastodon / Fediverse Publisher](PUB-030_mastodon-fediverse-publisher.md) — become cheap after this
- [PUB-051: Caption Prompt and Register Repair](archive/PUB-051_caption-prompt-and-register-repair.md) — added the `caption_angles` sidecar key the `SidecarDocument` must carry
- [PUB-005: Web Interface MVP](archive/PUB-005_web-interface-mvp.md), [PUB-025: Platform-Adaptive Captions](archive/PUB-025_platform-adaptive-captions.md)
- Prior fixes #134 (sidecar caption corruption), #147 (per-platform captions in UI)
- 2026-09-27 DRY review [#291](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/291): [#276](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/276), [#278](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/278), [#279](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/279), [#282](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/282), [#285](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/285) absorbed (Scope, AC12-AC17)

## Change Log

- 2026-09-27 — Folded in #209 and #210 so both can close as "tracked in PUB-059". Added what the spec lacked: the full module-global list, the lifespan failure-swallowing note, the eleven caption signatures, the `parse_model_json`/`PlatformCaptions`/`for_platforms` signatures, the test files and verification commands, and AC8 to AC11 (no import-time env read in `web/`; one service dependency and one CSP source; one shared sidecar model; autouse resets down to the db engine). AC4 now names "one publisher" as the third permitted touch point. Refreshed stale numbers from the audit at `main` 949b2d1: 20 route handlers in `web/app.py` (was 17; voice-profile routes added at `:864`/`:888`), nine image routes (was eight), `session_secret` at `:310` (was `:299`), voice-profile mutation at `:920` (was `:891`), `for_platforms` at `core/models.py:73` (was `:84-88`), `dict[str, Any]` at 92 (was 84), and 65 `dict[str, str]` occurrences in `src`. Added PUB-051's `caption_angles` (alongside `caption_generated` and `caption_submitted`) to the `SidecarDocument` scope and AC5.
- 2026-09-27 — Absorbed #276 (route prologue, curation ×3), #278 (publisher template), #279 (dead web surface), #282 (CLI preview sidecar/email copies) and #285 (service construction duplicates) from the DRY review (#291); added AC12-AC17. Effort grows from M toward L.
