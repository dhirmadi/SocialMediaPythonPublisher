# PUB-057: Configuration Consolidation

| Field | Value |
|-------|-------|
| **ID** | PUB-057 |
| **Category** | Config |
| **Priority** | P1 |
| **Effort** | L |
| **Status** | Proposal |
| **Dependencies** | PUB-056 |

## User Story

As a platform maintainer, I want one typed configuration model, one source for each platform limit, one boolean parser and a written precedence per field, so that a setting has one place to be defined and one place to be read.

## Problem

#97 removed INI and called the result a collapse. The review ([#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177), architecture A2) counts seven live channels: JSON env blobs and flags via `config/loader.py` (40 env reads; `load_application_config` 247 lines); `RuntimeSettings` (16 vars); orchestrator runtime v2 hand-mapped into `ApplicationConfig` by `_build_app_config_v2` (`config/source.py:453-595`, 141 lines) with `OrchestratorFeatures` mirroring `FeaturesConfig` field for field with different defaults; static YAML with a `PV2_STATIC_CONFIG_DIR` override; Pydantic defaults that duplicate the YAML and already diverge (telegram `hashtags` True in `static_loader.py:155`, false in the YAML; instagram style strings differ); `utils/captions.py:53-58` `_MAX_LEN` as a fifth copy of the limits; 25 raw `os.environ` reads outside `config/` ratified by `test_env_centralization.py`. Verified dead: `WebConfig.auth_enabled/auth_token/auth_user/auth_pass/admin_cookie_ttl_seconds`, `InstagramConfig.session_file`. Phantom: `services/ai.py:326` reads `vision_max_completion_tokens`, a field no model defines. Four bool parsers with three truthy sets; `rate_limit.py:124` says "do not unify". #143's injection is a convention: eleven `load_runtime_settings()` call sites, seven of them constructor fallbacks. No written precedence: Dropbox key from env and token from orchestrator; Auth0 client from env and policy from orchestrator; `CONFIGURATION.md` still documents an INI load order.

## Desired Outcome

No dead or phantom fields. Platform limits and styles defined once, in the in-package YAML. One `parse_bool`. `load_runtime_settings()` called exactly once per process. The orchestrator mapping generated from one schema, proposed in the orchestrator repo first. A precedence table per field with a test that every leaf field appears in it.

## Scope

**In scope (seven PRs):**
1. Delete the dead fields and the phantom key; make `vision_max_completion_tokens` a real `OpenAIConfig` field or delete the knob, and say which in the PR
2. One source for limits and styles: the in-package YAML, loaded once by `static_loader`; delete `_MAX_LEN` and the Python defaults for `platform_captions` and `PlatformLimitsConfig`; grep-based ratchet test
3. One `parse_bool` in `config/`; retire the other parsers; document the accepted truthy set once; alias table with a test if two variables genuinely need different sets
4. `RuntimeSettings` injected everywhere; seven fallbacks and the import-time call removed.
   **Note (2026-09-27 roadmap review):** the `get_service()` refactor and ~33 `cache_clear()` test
   sites are deferred to PUB-059, which deletes `get_service` entirely — doing the refactor here
   creates throwaway intermediate work. #173 is closed by PUB-059 instead.
5. `OrchestratorConfigV2` generated from `ApplicationConfig` (or one shared schema); orchestrator contract PR first
6. Precedence table in `docs_v2/05_Configuration/CONFIGURATION.md`; INI paragraphs deleted; test that every `ApplicationConfig` leaf field has a row
7. (added 2026-09-27, [#287](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/287)) Loader validates through the models: `OpenAIConfig.model_validate({**blob, "api_key": env})`, `ContentConfig.model_validate(blob or {})` and the same for captionfile/confirmation, so every default lives only in the Pydantic model (keep today's "empty system/role prompt falls back to default"); the Auth0 env construction in `loader.py` calls `web_env.load_web_and_auth0_from_env()`; `EmailConfig` is built from non-`None` values only, so `confirmation_tags_nature` is written once

**Widened 2026-09-27 (DRY review, [#291](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/291)):**
- Step 1 also deletes: all of `WebConfig` and `ApplicationConfig.web` (`web_env` returns `Auth0Config` only), `PlatformLimit.caption_target/subject_mode/max_hashtags`, `ConfirmationTagsConfig` and its YAML block, `OpenAIConfig.model`; `EnvConfigSource`, the `ConfigSource` protocol and the duplicated mode detection (the factory returns `OrchestratorConfigSource`, which also removes `hasattr(source, "check_connectivity")` in `web/app.py`); the INI leftovers (`config_file_path` plumbing — `app.py` warns once on `--config` — `log_config_source`, the INI-worded `None` checks); test-only `_safe_log_config`/`REDACT_KEYS` and `host_utils.extract_tenant` ([#288](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/288))
- Step 2 also covers UI and preview text: `web_ui_text.en.yaml` and `preview_text.yaml` are the only source, the Python defaults become empty and the template's `or "..."` fallbacks go ([#290](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/290)); `format_caption`'s four-way limit ladder becomes one lookup when `_MAX_LEN` goes (part of [#281](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/281))
- Step 3's alias table retires the `AUTO_VIEW` alias and the undocumented `SMTP_SERVER`/`SMTP_PORT` fallback (which silently builds `EmailConfig(sender="")`); confirm no Heroku config var still sets them before merging ([#288](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/288))
- Step 4 also moves the env reads inside `config/` (`OrchestratorConfigSource.__init__`: `RUNTIME_CONFIG_CACHE_MAX_SIZE`, `CREDENTIAL_CACHE_*`, `ORCHESTRATOR_PREFER_POST`, `ORCHESTRATOR_BASE_DOMAIN`) into `RuntimeSettings`, and `load_runtime_settings` uses one non-Optional `_env(name, default, cast)` ([#287](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/287))
- Step 5's orchestrator contract PR also drops `sd_caption_single_call_enabled` once PUB-058 has stopped reading it (leftover of [#280](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/280))

**Out of scope:**
- Web app factory (PUB-059)
- Dropbox fields if PUB-056 removed them

## Acceptance Criteria

- AC1: Given `config/schema.py`, when it is read, then no `WebConfig` auth field, `admin_cookie_ttl_seconds` or `session_file` exists, and `vision_max_completion_tokens` is either a declared field read directly or absent from `ai.py`
- AC2: Given `src`, when the ratchet test greps for numeric platform limits and style strings, then they occur only in the YAML
- AC3: Given `src`, when it is searched for bool-env parsing, then one function exists and every env truthy set is documented once
- AC4: Given a request or publish path, when `load_runtime_settings` is patched to raise, then nothing calls it (the existing `test_no_settings_reload_on_request_or_publish_paths` guard extended to lifespan-only)
- AC5: Given the orchestrator schema, when it changes a field, then `_build_app_config_v2` needs no hand edit because the mapping is generated; the orchestrator contract PR is merged and linked
- AC6: Given `ApplicationConfig`, when its leaf fields are enumerated, then each appears in the precedence table with env, orchestrator, static and default columns
- AC7: ~~Given the app's `RuntimeSettings` snapshot, when the `get_service()` dependency returns the `WebImageService`, then that service carries the same instance (identity, not equality), and the injection guard in `test_runtime_settings_injection.py` covers `web/dependencies.py` (#173)~~ — **Deferred to PUB-059** (roadmap review 2026-09-27): `get_service` is deleted there, not refactored here.
- AC8: Given `config/`, when it is searched, then `WebConfig`, `ApplicationConfig.web`, `EnvConfigSource`, the `ConfigSource` protocol and any `config_file_path` parameter are absent, and `--config` is still accepted with one warning
- AC9: Given a representative env, when `load_application_config` runs before and after step 7, then the resulting config is identical (snapshot test), and each default is defined once, in its model
- AC10: Given `web/templates/index.html` and the preview, when every UI/preview text key they use is enumerated, then each exists in its YAML and has no Python or template default
- AC11: Given this item ships, when its implementing PRs merge, then [#287](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/287), [#288](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/288) and [#290](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/290) are closed with `Closes #N` in the PR body; the step-2 and step-5 PRs say "Part of #281" / "Part of #280"

## Implementation Notes

- Sub-issue #206, six PRs in the listed order.
- Step 5 is the only one that touches the contract; propose it in `dhirmadi/platform-orchestrator` first and reference the PR.
- `test_env_centralization.py` becomes a ratchet in PUB-060; here it is only allowed to shrink.
- Tracker position: Phase 4, order 02 in #177.
- Test first, per step: a failing test that names the duplication (for example `test_platform_limits_defined_once`, `test_no_load_runtime_settings_outside_lifespan`, `test_every_config_field_has_precedence_row`), with the real-loader tests left unchanged.
- #173 test: extend `test_runtime_settings_injection.py` in the shape `TestCacheMissDoesNotReparseTheEnvironment` already uses for the tenant path. `get_service()` is a zero-argument `lru_cache(maxsize=1)` singleton (`web/dependencies.py:15`), so the signature change touches the ~33 `get_service.cache_clear()` sites in the tests; that is the work.
- **Code facts**: line numbers from the 2026-09-27 audit are in the Problem section and #206. They will drift as prior items land — the handoff doc should re-verify locations at implementation time, not rely on these numbers.
- Verification:

```bash
uv run ruff format --check . && uv run ruff check .
uv run mypy publisher_v2/src --ignore-missing-imports
WEB_SESSION_SECRET=x uv run pytest -q -p no:cacheprovider publisher_v2/tests/config
WEB_SESSION_SECRET=x uv run pytest -q -p no:cacheprovider
```

## Risks

- Deleting `_MAX_LEN` changes an import used by `format_caption`; read the YAML through `static_loader` once at import, not per call.
- Generated mapping must preserve the current defaults for a tenant that sends a partial payload; the characterisation for that is the existing `test_config_managed.py` suite.

## Success Metrics

- `os.environ` reads outside `config/` fall from 25 to the handful the alias table names.
- `load_runtime_settings` call sites fall from 11 to 2 (lifespan, CLI).

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issue [#206](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/206); closes [#173](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/173)
- [PUB-012: Centralized Config & i18n Text](archive/PUB-012_central-config-i18n.md), [PUB-021: Config Env Consolidation](archive/PUB-021_config-env-consolidation.md), [PUB-022: Orchestrator Schema V2 Integration](archive/PUB-022_orchestrator-schema-v2.md), [PUB-039: AI Caption Feature Flags & Voice Profile](archive/PUB-039_ai-caption-feature-flags.md)
- Prior fixes #97 (INI removal), #143 (runtime-settings injection)
- #206 and #173 were folded into this spec in full on 2026-09-27; either can be closed as "tracked in PUB-057".
- 2026-09-27 DRY review [#291](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/291): [#287](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/287), [#288](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/288), [#290](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/290) absorbed; parts of [#280](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/280) and [#281](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/281) (step 7, widened steps 1-5, AC8-AC11)

## Change Log

- 2026-09-27: Roadmap review — moved detailed code-facts (line numbers) from Implementation Notes to a handoff-time concern; they drift with each prior item landing.
- 2026-09-27: Folded GitHub #206/#173 in full; added: "say which" decision for `vision_max_completion_tokens`; YAML loaded once by `static_loader` and the named Python defaults (`platform_captions`, `PlatformLimitsConfig`); `parse_bool` located in `config/` with the truthy set documented once; `get_service.cache_clear()` test-site work; `CONFIGURATION.md` path; AC7 (#173 snapshot identity and guard coverage of `web/dependencies.py`); test-first names; tracker position; verification commands; 2026-09-27 code facts.
- 2026-09-27 — Absorbed #287 (loader restates schema defaults; config-internal env reads), #288 (never-run config paths and dead fields), #290 (UI/preview text in three copies) and parts of #280/#281 from the DRY review (#291): added step 7, widened steps 1-5, AC8-AC11. Effort grows from L toward XL, mostly deletion; consider splitting step 7 into its own PR sequence.
