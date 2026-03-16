# PUB-009: Feature Toggle System

| Field | Value |
|-------|-------|
| **ID** | PUB-009 |
| **Category** | Config |
| **Priority** | INF |
| **Effort** | S |
| **Status** | Done |
| **Dependencies** | — |

## Problem

Currently, all features are always active when the application runs. This makes it difficult to build and test new features in isolation, temporarily disable features for debugging or operational reasons, gradually roll out features to production, or reduce costs by disabling expensive operations (e.g., AI analysis) when not needed. There is no mechanism to control feature activation at runtime without modifying configuration files or code.

## Desired Outcome

Environment variable-based feature toggles for major application features. Operators can disable "AI Analyze and Caption" or "Publish" independently via env vars. Cloud provider/storage integration remains always enabled. Features default to enabled when not specified (backward compatible). Toggles are respected in both CLI and web interface workflows.

## Scope

- `FEATURE_ANALYZE_CAPTION` — toggles AI vision analysis and caption generation
- `FEATURE_PUBLISH` — toggles publishing to all platforms
- Storage/Dropbox is a required base feature; attempting to disable raises an error
- Toggles integrated into `ApplicationConfig` schema; read during config loading
- Workflow orchestrator and web service layer check toggles before executing AI/publish steps
- Toggle state logged at application startup

## Acceptance Criteria

- AC1: Given `FEATURE_ANALYZE_CAPTION=false`, when the workflow executes, AI vision analysis and caption generation are skipped; workflow proceeds with image selection and storage only
- AC2: Given `FEATURE_PUBLISH=false`, when the workflow executes, publishing to all platforms is skipped; analysis and captioning (if enabled) still occur
- AC3: Given no feature toggle env vars are set, all features behave as before (backward compatible)
- AC4: Given both toggles false, only image selection and storage operations occur
- AC5: Given feature toggles set via env vars, the web interface respects them in API endpoints
- AC6: Given a feature disabled via toggle, preview mode reflects the disabled state (e.g., "Analysis skipped" or "Publish skipped")
- AC7: Given storage/Dropbox is attempted to be disabled, configuration loading raises an error

## Implementation Notes

- Toggle values: boolean (true/false, 1/0, yes/no, case-insensitive)
- Feature toggles distinct from platform enablement flags (telegram_enabled, instagram_enabled, etc.)
- Web UI may hide/disable controls for disabled features (future enhancement; MVP uses env vars only)
- Dependencies: `publisher_v2.config.loader`, `publisher_v2.config.schema`, `WorkflowOrchestrator`, web service layer

## Related

- [Original feature doc](../../08_Epics/003_runtime_controls_telemetry/009_feature_toggle/009_feature.md) — full historical detail
