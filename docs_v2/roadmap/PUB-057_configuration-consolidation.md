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

**In scope (six PRs):**
1. Delete the dead fields and the phantom key; make `vision_max_completion_tokens` a real `OpenAIConfig` field or delete the knob
2. One source for limits and styles; delete `_MAX_LEN` and the Python defaults; grep-based ratchet test
3. One `parse_bool`; alias table with a test if two variables genuinely need different sets
4. `RuntimeSettings` injected everywhere; seven fallbacks and the import-time call removed; `web/dependencies.get_service()` receives the snapshot (closes #173)
5. `OrchestratorConfigV2` generated from `ApplicationConfig` (or one shared schema); orchestrator contract PR first
6. Precedence table in `CONFIGURATION.md`; INI paragraphs deleted; test that every `ApplicationConfig` leaf field has a row

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

## Implementation Notes

- Sub-issue #206, six PRs in the listed order.
- Step 5 is the only one that touches the contract; propose it in `dhirmadi/platform-orchestrator` first and reference the PR.
- `test_env_centralization.py` becomes a ratchet in PUB-060; here it is only allowed to shrink.

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
