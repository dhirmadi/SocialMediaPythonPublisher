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

Review [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177), architecture A5 to A7:

- `web/app.py:329-917` defines 17 routes (index, three health, admin status and logout, eight image routes, four config routes); `routers/` holds only `auth` and `library`.
- Fourteen module-level mutable globals in `src`, including three limiters (`app.py:74-76`), an import-time `session_secret` read that raises without a secret (`:299`; `conftest.py:29` must `setdefault` it before any import), `_REVOKED_SIDS`, `_PUBLISH_LOCKS`, two library rate dicts, the `oauth` registry, the shared http client, the engine and session factory, plus two `lru_cache` singletons. `conftest.py:117-206` needs three autouse fixtures to reset them.
- Three wiring styles: `Depends(get_request_service)` with an `lru_cache` fallback; settings via `app.state` with an env-reparse fallback; auth via env reads inside `require_admin`; CSP origins from `app.state` in standalone but `request.state` in orchestrated mode.
- `dict[str, str]` for captions in eleven signatures; three platforms hard-coded in `CaptionSpec.for_platforms` (`core/models.py:84-88`); 84 `dict[str, Any]`; the sidecar writer builds text and the parser re-parses it defensively with a repr-recovery path for a past bug; `web/app.py:891` mutates `service.config.content.voice_profile` in place; ten `getattr(config.x, "field", default)` sites exist because fixtures pass `SimpleNamespace` stand-ins; `PublishResponse.results` is `dict[str, dict[str, Any]]` and `AnalysisResponse` re-lists `ImageAnalysis` fields by hand.

## Desired Outcome

`create_app(settings) -> FastAPI` with limiters, revocation set, templates, secret, oauth registry and publish locks as instance state; `routers/images.py` and `routers/config.py`; one service dependency; one CSP origin source. A `Platform` StrEnum and `PlatformCaptions` used end to end; a `SidecarDocument` model shared by writer and parser; a frozen `ApplicationConfig` with request-scoped overrides; fixtures that build real config objects; response models derived from domain types.

## Scope

**In scope:**
- App factory; module `app` kept importable for uvicorn (Procfile unchanged unless the owner approves a factory target)
- Image and config routes moved to routers; `get_service` deleted; CSP origins unified
- conftest autouse resets reduced to those still needed
- `Platform` enum; `PlatformCaptions`; `for_platforms` without a hard-coded list
- `SidecarDocument` model; repr-recovery kept behind a flag until a fixture check shows no legacy sidecars
- One `parse_model_json` helper for the four `ai.py` parse sites
- Frozen `ApplicationConfig`; voice-profile override as request-scoped service state
- Fixtures build real config; `getattr` defaults deleted
- `PublishResponse.results: dict[Platform, PublishResult]`; `AnalysisResponse` derived from `ImageAnalysis`
- Ratchets on module-level globals and `dict[str, Any]` occurrences

**Out of scope:**
- New platforms themselves (PUB-027, PUB-030 become one-enum-entry items after this)
- Template redesign

## Acceptance Criteria

- AC1: Given two apps created with different settings in one process, when each is driven, then limiter and revocation state are not shared
- AC2: Given `WEB_SESSION_SECRET` is unset, when `publisher_v2.web.app` is imported, then no exception is raised; when `create_app` is called, then it raises naming the variable
- AC3: Given `web/app.py`, when its routes are listed, then no image or config route is defined there
- AC4: Given the enum gains a fourth platform and the YAML an entry, when `for_platforms` and the sidecar round-trip run parametrised over the enum, then no other change is needed
- AC5: Given every field type the sidecar supports, when the writer output is parsed, then the round-trip is identity; given legacy fixtures, then they still parse
- AC6: Given `src`, when it is searched, then no `getattr(..., "field", default)` on a config object and no `dict[str, str]` caption signature remains
- AC7: Given the ratchets, when each PR merges, then the module-level global count and the `dict[str, Any]` count are not higher than before

## Implementation Notes

- Two sub-issues: #209 (factory and routers), #210 (types). After PUB-057 step 4 (settings injection) and PUB-058.
- A Procfile change to a factory target is an ask-first item; prefer `app = create_app(load_runtime_settings())` at module bottom guarded so import stays side-effect free.

## Risks

- The template's JavaScript calls routes by path; moving routes must keep every path identical (assert with a route-table snapshot test).
- Freezing `ApplicationConfig` breaks any test that mutates it; those tests are the ones this item wants to find.

## Success Metrics

- conftest autouse fixtures down from three to one.
- PUB-027 and PUB-030 re-scoped to S after this lands.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issues [#209](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/209), [#210](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/210)
- [PUB-027: Bluesky Publisher](PUB-027_bluesky-publisher.md), [PUB-030: Mastodon / Fediverse Publisher](PUB-030_mastodon-fediverse-publisher.md) — become cheap after this
- [PUB-005: Web Interface MVP](archive/PUB-005_web-interface-mvp.md), [PUB-025: Platform-Adaptive Captions](archive/PUB-025_platform-adaptive-captions.md)
- Prior fixes #134 (sidecar caption corruption), #147 (per-platform captions in UI)
