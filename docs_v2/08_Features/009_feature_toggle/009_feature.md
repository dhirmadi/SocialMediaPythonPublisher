<!-- docs_v2/08_Features/08_01_Feature_Request/009_feature-toggle.md -->

# Feature Toggle System

**ID:** 009  
**Name:** feature-toggle  
**Status:** Proposed  
**Date:** 2025-01-27  
**Author:** User Request  

## Summary
This feature adds a feature toggle system that allows operators to enable or disable major application features via environment variables. This enables building and testing new features independently, and provides operational control over feature activation without code changes. The two primary features that can be toggled are "AI Analyze and Caption" and "Publish". The cloud provider integration (storage/Dropbox) is considered the base feature and must always remain enabled.

## Problem Statement
Currently, all features are always active when the application runs. This makes it difficult to:
- Build and test new features in isolation
- Temporarily disable features for debugging or operational reasons
- Gradually roll out features to production
- Reduce costs by disabling expensive operations (e.g., AI analysis) when not needed

There is no mechanism to control feature activation at runtime without modifying configuration files or code.

## Goals
- Add environment variable-based feature toggles for major application features
- Support toggling "AI Analyze and Caption" feature independently
- Support toggling "Publish" feature independently
- Ensure cloud provider/storage integration remains always enabled (base feature)
- Maintain backward compatibility: features default to enabled if not specified
- Integrate feature toggles into existing configuration system
- Respect feature toggles in both CLI and web interface workflows

## Non-Goals
- Adding feature toggles for individual platform publishers (Telegram, Instagram, Email) - these are already controlled via platform enablement flags
- Adding feature toggles for sub-features (e.g., SD caption generation) - these remain controlled by existing config flags
- Implementing a feature flag service or remote configuration system
- Adding feature toggle UI controls in the web interface (environment variables only)
- Changing how preview mode or dry-run mode work

## Users & Stakeholders
- Primary users: Operators running the application in various environments (development, staging, production)
- Developers: Building and testing new features that can be isolated via toggles
- Operations: Controlling feature activation for cost management, debugging, or gradual rollouts

## User Stories
- As an operator, I want to disable AI analysis and captioning via an environment variable, so I can test storage-only workflows without incurring OpenAI API costs.
- As an operator, I want to disable publishing via an environment variable, so I can run analysis-only workflows for content review.
- As a developer, I want to build a new feature that can be toggled independently, so I can test it without affecting other features.
- As an operator, I want feature toggles to default to enabled, so existing deployments continue working without changes.

## Acceptance Criteria (BDD-style)
- Given the `FEATURE_ANALYZE_CAPTION=false` environment variable is set, when the workflow executes, then AI vision analysis and caption generation must be skipped, and the workflow must proceed with image selection and storage operations only.
- Given the `FEATURE_PUBLISH=false` environment variable is set, when the workflow executes, then publishing to all platforms must be skipped, but analysis and captioning (if enabled) must still occur.
- Given no feature toggle environment variables are set, when the workflow executes, then all features must behave as they currently do (backward compatible).
- Given both `FEATURE_ANALYZE_CAPTION=false` and `FEATURE_PUBLISH=false` are set, when the workflow executes, then only image selection and storage operations must occur (no AI, no publishing).
- Given feature toggles are set via environment variables, when the web interface is used, then the same feature toggles must be respected in web API endpoints.
- Given a feature is disabled via toggle, when preview mode is used, then preview output must reflect the disabled state (e.g., show "Analysis skipped" or "Publish skipped").
- Given storage/Dropbox operations are attempted to be disabled, when configuration is loaded, then an error must be raised indicating that storage is a required base feature.

## UX / Content Requirements
- Feature toggles are controlled via environment variables only (no UI changes required for MVP)
- When features are disabled, log messages should clearly indicate which features were skipped
- Preview mode output should show when features are disabled
- Error messages should be clear if invalid toggle values are provided

## Technical Requirements
- Feature toggles must be read from environment variables during configuration loading
- Toggle values must be boolean (true/false, 1/0, yes/no, case-insensitive)
- Feature toggles must be integrated into `ApplicationConfig` schema
- Workflow orchestrator must check feature toggles before executing AI analysis/captioning and publishing steps
- Web service layer must respect feature toggles when handling analyze and publish requests
- Feature toggle state must be logged at application startup for observability

## Dependencies
- Existing configuration system (`publisher_v2.config.loader`, `publisher_v2.config.schema`)
- Workflow orchestrator (`publisher_v2.core.workflow`)
- Web service layer (`publisher_v2.web.service`, `publisher_v2.web.app`)

## Risks & Mitigations
- **Risk:** Breaking existing deployments if toggles default incorrectly  
  **Mitigation:** Default all toggles to enabled (true) to maintain backward compatibility
- **Risk:** Confusion about which features can be toggled  
  **Mitigation:** Clear documentation and error messages indicating storage cannot be disabled
- **Risk:** Web UI showing options for disabled features  
  **Mitigation:** Web UI should respect toggles and hide/disable relevant controls (future enhancement, not in scope for MVP)

## Open Questions
- Should feature toggles be configurable via INI file in addition to environment variables? (Decision: Environment variables only for MVP, can be extended later)
- Should there be a way to query feature toggle state via API? (Decision: Not required for MVP, can be added if needed)

## Related Features
- Feature 005: Web Interface MVP (web endpoints must respect toggles)
- Feature 001: Caption File (AI analysis toggle affects caption generation)

## Notes
- Feature toggles are distinct from platform enablement flags (telegram_enabled, instagram_enabled, etc.)
- Storage/Dropbox is considered infrastructure, not a feature, and must always be enabled
- This feature enables future features to be built with toggle support from the start

