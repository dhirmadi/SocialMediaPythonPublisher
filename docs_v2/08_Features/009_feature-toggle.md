<!-- docs_v2/08_Features/009_feature-toggle.md -->

# Feature Toggle System — Final Documentation

**Feature ID:** 009  
**Name:** feature-toggle  
**Status:** Shipped  
**Date:** 2025-01-27  

---

## Summary
Introduced environment-variable-driven feature toggles that allow operators to independently enable or disable the AI analysis/captioning pipeline and the publishing pipeline without modifying code or INI files. Storage/Dropbox remains the immutable base feature. Toggles apply uniformly across the CLI workflow and the FastAPI web interface, enabling safer rollouts, selective testing, and cost controls.

## Goals
- Provide `FEATURE_ANALYZE_CAPTION` and `FEATURE_PUBLISH` environment variables with sane defaults (enabled) and strict validation.
- Gate WorkflowOrchestrator analysis/caption and publish steps using the toggles.
- Reflect toggle state in preview output, structured logs, and web responses.
- Add targeted tests covering config parsing, workflow gating, web service behavior, and preview UX updates.

## Non-Goals
- Fine-grained toggles per individual publisher or sub-feature (e.g., SD caption metadata).
- Remote feature-flag service or UI controls.
- Ability to disable Dropbox/storage (always required).

## User Value
- **Cost Control:** Turn off AI analysis/captioning to avoid OpenAI spend during storage-only maintenance.
- **Safety:** Disable publishing channel-wide while continuing to review AI output via preview or the web app.
- **Rollout Flexibility:** Build new features while leaving existing ones disabled until ready without redeploying code.

## Technical Overview
- Added `FeaturesConfig` (Pydantic) to `ApplicationConfig` holding `analyze_caption_enabled` and `publish_enabled`.
- `load_application_config` now parses `FEATURE_ANALYZE_CAPTION` and `FEATURE_PUBLISH` via a shared boolean parser with strict validation.
- `WorkflowOrchestrator` skips vision analysis/caption generation and/or publisher execution based on the toggles, emitting `feature_*_skipped` logs and avoiding side effects (sidecar writes, archives).
- `WebImageService` honors toggles: analyze returns cached/empty responses when disabled; publish returns `PermissionError` which web routes translate to HTTP 403.
- Preview utilities gained `feature_enabled` flags to surface "skipped" messaging, and CLI preview mode prints current toggle state plus startup JSON logging.

## Implementation Details
- Files touched:
  - `publisher_v2/src/publisher_v2/config/schema.py`, `config/loader.py`
  - `publisher_v2/src/publisher_v2/core/workflow.py`
  - `publisher_v2/src/publisher_v2/web/service.py`, `web/app.py`
  - `publisher_v2/src/publisher_v2/utils/preview.py`, `app.py`
  - Docs: `docs_v2/05_Configuration/CONFIGURATION.md`, `docs_v2/03_Architecture/ARCHITECTURE.md`
  - Tests: new workflow + preview + web test cases, config loader coverage
- New structured logs: `feature_analyze_caption_skipped`, `feature_caption_generation_skipped`, `feature_publish_skipped`, `feature_toggles_loaded`, `web_feature_*`.
- Preview mode always reports toggle state and still computes per-platform formatting while warning if publish is disabled.

## Testing
- `poetry run pytest publisher_v2/tests/test_config_loader.py publisher_v2/tests/test_workflow_feature_toggles.py publisher_v2/tests/web/test_web_service.py publisher_v2/tests/test_preview_helpers_more.py`
- Coverage focus: config parsing, workflow gating (analysis + publish), web service behavior, preview output messaging.
- Existing suites continue to pass; warning about `asyncio_default_fixture_loop_scope` is pre-existing.

## Rollout Notes
- No config migration required; toggles default to enabled.
- Operators can set toggles via environment variables and restart the CLI/web process to apply.
- Preview and web UI clearly indicate when features are disabled to avoid confusion.

## Artifacts
- Feature Request: `docs_v2/08_Features/08_01_Feature_Request/009_feature-toggle.md`
- Feature Design: `docs_v2/08_Features/08_02_Feature_Design/009_feature-toggle_design.md`
- Plan: `docs_v2/08_Features/08_03_Feature_plan/009_feature-toggle_plan.yaml`
- Critical Review: `docs_v2/09_Reviews/009_feature-toggle_review.md`
- Final Doc (this file)

