<!-- docs_v2/08_Features/08_02_Feature_Design/009_feature-toggle_design.md -->

# Feature Toggle System — Feature Design

**Feature ID:** 009  
**Feature Name:** feature-toggle  
**Design Version:** 1.0  
**Date:** 2025-01-27  
**Status:** Design Review  
**Author:** Architecture Team  

---

## 1. Summary

### Problem
The application currently has no mechanism to enable or disable major features at runtime. All features (AI analysis/captioning, publishing) are always active, making it difficult to:
- Build and test features independently
- Temporarily disable features for debugging or cost control
- Gradually roll out features

### Goals
1. Add environment variable-based feature toggles for "AI Analyze and Caption" and "Publish" features
2. Ensure storage/Dropbox integration remains always enabled (base feature)
3. Maintain full backward compatibility (features default to enabled)
4. Integrate toggles into existing configuration and workflow systems
5. Respect toggles in both CLI and web interface workflows

### Non-Goals
- Feature toggles for individual platform publishers (already handled by platform enablement flags)
- Feature toggles for sub-features (SD caption, extended metadata, etc.)
- Remote feature flag service or UI controls
- Changing preview mode or dry-run behavior

---

## 2. Context & Assumptions

### Current State
- **Configuration System:** INI files + `.env` for secrets, loaded via `publisher_v2.config.loader.load_application_config()`
- **Config Schema:** Pydantic v2 models in `publisher_v2.config.schema.ApplicationConfig`
- **Workflow:** `WorkflowOrchestrator.execute()` orchestrates: select → analyze → caption → publish → archive
- **Web Interface:** FastAPI endpoints in `publisher_v2.web.app` delegate to `WebImageService`
- **Feature Boundaries:**
  - AI Analysis/Captioning: Steps 3-4 in workflow (vision analysis + caption generation)
  - Publishing: Step 5 in workflow (parallel publishing to enabled platforms)
  - Storage: Steps 1-2, 6 (image selection, download, archive) - base feature

### Constraints
1. Python 3.9–3.12 compatibility
2. Backward compatibility: existing deployments must work without changes
3. Environment variables only (no INI file support for MVP)
4. Storage cannot be disabled (hard requirement)
5. Toggles must work in both CLI and web workflows

### Dependencies
- Existing: `publisher_v2.config.loader`, `publisher_v2.config.schema`
- Existing: `publisher_v2.core.workflow.WorkflowOrchestrator`
- Existing: `publisher_v2.web.service.WebImageService`
- No new external dependencies

### Assumptions
1. Environment variables are the preferred mechanism for feature toggles (operational control)
2. Boolean values can be parsed flexibly (true/false, 1/0, yes/no, case-insensitive)
3. Default behavior (when toggle not set) is enabled (backward compatible)
4. Feature toggles are read once at startup during config loading

---

## 3. Requirements

### Functional Requirements

**FR1: Feature Toggle Configuration**
- Add `FeaturesConfig` model to `publisher_v2.config.schema`
- Fields: `analyze_caption_enabled: bool = True`, `publish_enabled: bool = True`
- Load from environment variables: `FEATURE_ANALYZE_CAPTION`, `FEATURE_PUBLISH`
- Parse boolean values flexibly (true/false, 1/0, yes/no, case-insensitive)
- Default to `True` if environment variable not set (backward compatible)

**FR2: Workflow Integration**
- `WorkflowOrchestrator.execute()` must check `config.features.analyze_caption_enabled` before steps 3-4
- If disabled, skip vision analysis and caption generation; set `analysis = None`, `caption = ""`
- `WorkflowOrchestrator.execute()` must check `config.features.publish_enabled` before step 5
- If disabled, skip publishing; set `publish_results = {}`, `any_success = False`
- Archive step (step 6) must respect `any_success` (if publish disabled, archive skipped)

**FR3: Web Interface Integration**
- `WebImageService.analyze_and_caption()` must check feature toggle before calling AI service
- If disabled, return cached sidecar data if available, or return empty analysis response
- `WebImageService.publish_image()` must check feature toggle before calling orchestrator
- If disabled, return error response indicating publish is disabled
- Web endpoints must respect toggles consistently with CLI behavior

**FR4: Preview Mode Support**
- Preview mode output must show when features are disabled
- `preview_utils` functions should handle `analysis = None` and `caption = ""` gracefully
- Show clear indicators like "Analysis skipped (feature disabled)" or "Publish skipped (feature disabled)"

**FR5: Logging & Observability**
- Log feature toggle state at application startup (INFO level)
- Log when features are skipped due to toggles (INFO level)
- Include feature toggle state in workflow timing logs

**FR6: Validation**
- Storage/Dropbox cannot be disabled (hard validation error if attempted)
- Invalid toggle values should raise clear configuration errors

### Non-Functional Requirements

**NFR1: Performance**
- Feature toggle checks must be O(1) boolean checks (no performance impact)
- No additional API calls or I/O for toggle evaluation

**NFR2: Backward Compatibility**
- Default behavior unchanged: all features enabled if toggles not set
- Existing config files and deployments continue working without modification

**NFR3: Maintainability**
- Feature toggles clearly separated from platform enablement flags
- Clear naming convention: `FEATURE_<NAME>` for environment variables
- Documentation updated to explain toggle usage

---

## 4. Architecture & Design

### 4.1 Configuration Schema Changes

**New Model: `FeaturesConfig`**
```python
class FeaturesConfig(BaseModel):
    analyze_caption_enabled: bool = Field(
        default=True,
        description="Enable AI vision analysis and caption generation feature"
    )
    publish_enabled: bool = Field(
        default=True,
        description="Enable publishing feature (all platforms)"
    )
```

**Updated Model: `ApplicationConfig`**
```python
class ApplicationConfig(BaseModel):
    dropbox: DropboxConfig
    openai: OpenAIConfig
    platforms: PlatformsConfig
    features: FeaturesConfig = FeaturesConfig()  # New field
    # ... rest unchanged
```

### 4.2 Configuration Loader Changes

**Environment Variable Parsing**
- Read `FEATURE_ANALYZE_CAPTION` (default: "true" or not set → True)
- Read `FEATURE_PUBLISH` (default: "true" or not set → True)
- Parse with flexible boolean parsing function:
  - `True`: "true", "1", "yes", "on" (case-insensitive)
  - `False`: "false", "0", "no", "off" (case-insensitive)
- Raise `ConfigurationError` for invalid values

**Loader Function Updates**
- `load_application_config()` creates `FeaturesConfig` instance
- Pass to `ApplicationConfig` constructor

### 4.3 Workflow Orchestrator Changes

**Step 3-4: AI Analysis & Captioning**
```python
# Before step 3
if self.config.features.analyze_caption_enabled:
    analysis = await self.ai_service.analyzer.analyze(temp_link)
    caption, sd_caption = await self.ai_service.create_caption_pair_from_analysis(analysis, spec)
else:
    analysis = None
    caption = ""
    sd_caption = None
    log_json(..., "feature_analyze_caption_skipped", ...)
```

**Step 5: Publishing**
```python
# Before step 5
if self.config.features.publish_enabled:
    # Existing publish logic
    enabled_publishers = [p for p in self.publishers if p.is_enabled()]
    # ... publish ...
else:
    publish_results = {}
    log_json(..., "feature_publish_skipped", ...)
```

**Step 6: Archive**
- Archive logic already depends on `any_success`
- If publish disabled, `any_success = False`, so archive skipped automatically
- No changes needed

### 4.4 Web Service Changes

**`WebImageService.analyze_and_caption()`**
```python
async def analyze_and_caption(...) -> AnalysisResponse:
    if not self.config.features.analyze_caption_enabled:
        # Return cached sidecar if available, or empty response
        blob = await self.storage.download_sidecar_if_exists(...)
        if blob:
            # Return cached data
        return AnalysisResponse(..., caption="", description="", ...)
    # Existing logic
```

**`WebImageService.publish_image()`**
```python
async def publish_image(...) -> PublishResponse:
    if not self.config.features.publish_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Publish feature is disabled via FEATURE_PUBLISH toggle"
        )
    # Existing logic
```

### 4.5 Preview Mode Changes

**Preview Output Updates**
- `preview_utils.print_vision_analysis()`: Handle `analysis = None` gracefully
- `preview_utils.print_caption()`: Handle empty caption gracefully
- Add indicators: "⚠ Analysis skipped (FEATURE_ANALYZE_CAPTION=false)"
- Add indicators: "⚠ Publish skipped (FEATURE_PUBLISH=false)"

### 4.6 Logging Updates

**Startup Logging**
```python
log_json(
    logger,
    logging.INFO,
    "feature_toggles_loaded",
    analyze_caption_enabled=config.features.analyze_caption_enabled,
    publish_enabled=config.features.publish_enabled,
)
```

**Workflow Logging**
- Add `feature_analyze_caption_skipped` event when analysis skipped
- Add `feature_publish_skipped` event when publish skipped

---

## 5. Implementation Plan

### Phase 1: Configuration Schema & Loader
1. Add `FeaturesConfig` model to `schema.py`
2. Add `features` field to `ApplicationConfig`
3. Update `loader.py` to read environment variables and create `FeaturesConfig`
4. Add boolean parsing utility function
5. Add validation (storage cannot be disabled)

### Phase 2: Workflow Integration
1. Update `WorkflowOrchestrator.execute()` to check `analyze_caption_enabled` before steps 3-4
2. Update `WorkflowOrchestrator.execute()` to check `publish_enabled` before step 5
3. Add logging for skipped features
4. Ensure archive logic respects disabled publish

### Phase 3: Web Interface Integration
1. Update `WebImageService.analyze_and_caption()` to check toggle
2. Update `WebImageService.publish_image()` to check toggle and return error if disabled
3. Ensure web endpoints return appropriate responses

### Phase 4: Preview Mode Updates
1. Update preview utilities to handle disabled features gracefully
2. Add visual indicators for disabled features

### Phase 5: Testing
1. Unit tests for configuration loading (various boolean formats)
2. Integration tests for workflow with toggles disabled
3. Web API tests for disabled features
4. Preview mode tests with disabled features

---

## 6. Data Model Changes

### Configuration Model
- **New:** `FeaturesConfig` model
- **Updated:** `ApplicationConfig` includes `features: FeaturesConfig`

### No Data Storage Changes
- Feature toggles are runtime configuration only
- No database or file changes required

---

## 7. API Changes

### CLI
- No CLI argument changes
- Behavior changes based on environment variables only

### Web API
- **`POST /api/images/{filename}/analyze`**: Returns empty analysis if feature disabled
- **`POST /api/images/{filename}/publish`**: Returns 403 if feature disabled

### Internal APIs
- `WorkflowOrchestrator.execute()`: Accepts `ApplicationConfig` with `features` field
- `WebImageService`: Accepts `ApplicationConfig` with `features` field

---

## 8. Error Handling

### Configuration Errors
- Invalid toggle value: `ConfigurationError` with clear message
- Attempt to disable storage: `ConfigurationError` with message explaining storage is required

### Runtime Errors
- Disabled publish via web API: HTTP 403 with clear error message
- Disabled analysis: Return empty analysis response (not an error)

---

## 9. Testing Strategy

### Unit Tests
- Configuration loader: various boolean formats (true/false, 1/0, yes/no, case variations)
- Configuration loader: default behavior (not set → True)
- Configuration loader: invalid values raise errors

### Integration Tests
- Workflow with `analyze_caption_enabled=false`: verify analysis skipped, workflow continues
- Workflow with `publish_enabled=false`: verify publish skipped, archive skipped
- Workflow with both disabled: verify only image selection/storage occurs
- Preview mode with disabled features: verify output shows skipped indicators

### Web API Tests
- `POST /api/images/{filename}/analyze` with feature disabled: verify empty response
- `POST /api/images/{filename}/publish` with feature disabled: verify 403 error
- Verify web behavior matches CLI behavior

### Edge Cases
- Toggle enabled but AI service unavailable: existing error handling applies
- Toggle enabled but no publishers enabled: existing behavior (no publish results)
- Toggle disabled but preview mode: verify preview shows skipped state

---

## 10. Migration & Rollout

### Migration Path
1. Deploy code changes (toggles default to enabled)
2. Existing deployments continue working unchanged
3. Operators can opt-in to using toggles via environment variables

### Rollout Plan
1. Deploy to development/staging
2. Test with toggles enabled (default) - verify no regressions
3. Test with toggles disabled - verify expected behavior
4. Deploy to production
5. Document toggle usage for operators

### Rollback Plan
- Revert code changes if issues arise
- Toggles default to enabled, so reverting restores original behavior

---

## 11. Documentation Updates

### Configuration Documentation
- Update `docs_v2/05_Configuration/CONFIGURATION.md` with feature toggle section
- Document environment variables: `FEATURE_ANALYZE_CAPTION`, `FEATURE_PUBLISH`
- Document default behavior and boolean value formats

### Architecture Documentation
- Update `docs_v2/03_Architecture/ARCHITECTURE.md` to mention feature toggles
- Document that storage is base feature and cannot be disabled

### User Documentation
- Add examples of using toggles for cost control and debugging
- Document preview mode behavior with disabled features

---

## 12. Success Criteria

### Functional
- ✅ Feature toggles can be set via environment variables
- ✅ Workflow respects toggles in CLI mode
- ✅ Web interface respects toggles
- ✅ Preview mode shows disabled feature indicators
- ✅ Backward compatibility maintained (default enabled)

### Non-Functional
- ✅ No performance impact (O(1) boolean checks)
- ✅ Clear logging and observability
- ✅ Comprehensive test coverage
- ✅ Documentation updated

---

## 13. Open Questions & Decisions

### Decisions Made
1. **Environment variables only (no INI support)**: Simpler for MVP, can be extended later
2. **Default enabled**: Maintains backward compatibility
3. **Storage cannot be disabled**: Hard requirement, validated at config load time
4. **Web API returns 403 for disabled publish**: Clear error vs. silent skip

### Open Questions
- None for MVP scope

---

## 14. References

- Feature Request: `docs_v2/08_Features/08_01_Feature_Request/009_feature-toggle.md`
- Configuration Schema: `publisher_v2/src/publisher_v2/config/schema.py`
- Configuration Loader: `publisher_v2/src/publisher_v2/config/loader.py`
- Workflow Orchestrator: `publisher_v2/src/publisher_v2/core/workflow.py`
- Web Service: `publisher_v2/src/publisher_v2/web/service.py`

