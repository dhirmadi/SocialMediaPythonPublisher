<!-- docs_v2/08_Features/08_04_ChangeRequests/001/002_design.md -->

# SD Caption AI Service Integration — Change Design

**Feature ID:** 001  
**Change ID:** 001-002  
**Parent Feature:** Stable Diffusion Caption File  
**Design Version:** 1.0  
**Date:** 2025-11-20  
**Status:** Design Review  
**Author:** TODO  
**Linked Change Request:** docs_v2/08_Features/08_04_ChangeRequests/001/002_sd-caption-ai-service-integration.md  
**Parent Feature Design:** docs_v2/08_Features/08_02_Feature_Design/001_captionfile_design.md  

## 1. Summary

- Problem & context: The captionfile feature defines a single-call `{caption, sd_caption}` flow via `CaptionGeneratorOpenAI.generate_with_sd`, but key callers (CLI workflow and web service) still invoke `CaptionGeneratorOpenAI` directly, bypassing `AIService` and its shared rate limiting and error handling. This fragments SD caption behavior and makes it harder to evolve consistently across interfaces.  
- Goals & Non-goals: This change centralizes all Stable Diffusion caption generation behind `AIService` while preserving public behavior, configuration, and sidecar semantics. It avoids duplicating analysis work and keeps sidecar creation/archival logic in existing components.

## 2. Context & Assumptions

- Current behavior (affected parts):
  - `services.ai.CaptionGeneratorOpenAI` exposes `generate` (caption-only) and `generate_with_sd` (returns `{caption, sd_caption}` JSON).  
  - `services.ai.AIService`:
    - `create_caption(url_or_bytes, spec)` — runs analysis + caption via analyzer + generator with shared `AsyncRateLimiter`.  
    - `create_caption_pair(url_or_bytes, spec)` — runs analysis + single-call caption+SD pair, then falls back to caption-only when SD is disabled or fails.  
  - `core.workflow.WorkflowOrchestrator.execute`:
    - Calls `ai_service.analyzer.analyze(temp_link)` directly.  
    - Calls `ai_service.generator.generate_with_sd` or `generate` directly based on config, with local retry/fallback logic and logging.  
  - `web.service.WebImageService.analyze_and_caption`:
    - Calls `ai_service.analyzer.analyze(temp_link)` directly.  
    - Calls `ai_service.generator.generate_with_sd` or `generate` directly with its own error handling and logging.  
- Constraints from the parent feature:
  - Config flags `sd_caption_enabled`, `sd_caption_single_call_enabled`, `sd_caption_model`, and prompt settings remain the authoritative controls for SD caption behavior.  
  - SD caption generation is best-effort and must not break the main publishing pipeline; a failure must fall back to caption-only.  
  - Sidecar creation semantics (writer format, archive behavior, preview visibility) must not change.  
- Dependencies:
  - `AIService` is already constructed once and shared between workflow and web layers.  
  - Existing tests (`test_ai_sd_generate.py`, `test_workflow_sd_integration.py`, `test_e2e_sd_caption.py`, web tests) rely on current observable behavior and must continue to pass.

## 3. Requirements

### 3.1 Functional Requirements

- **CR1:** Ensure all SD caption generation in the workflow and web layers invokes a documented `AIService` method instead of calling `CaptionGeneratorOpenAI` directly.  
- **CR2:** Preserve existing behavior for caption-only paths when SD caption is disabled or when single-call `{caption, sd_caption}` fails, including fallbacks and logging patterns.  
- **CR3:** Maintain the single-call `{caption, sd_caption}` contract where enabled, without changing prompt content, response JSON structure, or sidecar contents.  
- **CR4:** Keep the ability to use caption-only flows (`generate`) from `AIService` for callers that do not require SD captions.

### 3.2 Non-Functional Requirements

- Rate limiting and retry behavior for SD captions must be unified via `AIService` for both CLI and web flows; individual call sites must not re-implement retry loops.  
- Error handling must remain explicit and observable via structured logs, with consistent event names for SD caption start/complete/error.  
- No measurable latency or cost regressions are allowed; the number of OpenAI calls per image must remain unchanged.  

## 4. Architecture & Design (Delta)

### 4.1 Current vs. Proposed

- Current:
  - `AIService.create_caption_pair` encapsulates a full analyze + caption+SD flow but is unused by orchestrator and web service.  
  - Workflow and web flows invoke `VisionAnalyzerOpenAI.analyze` directly and then call `CaptionGeneratorOpenAI.generate_with_sd` / `generate` with duplicated fallback logic and without the shared `AsyncRateLimiter`.  
- Proposed:
  - Introduce a new `AIService` helper, e.g. `create_caption_pair_from_analysis(analysis: ImageAnalysis, spec: CaptionSpec) -> tuple[str, Optional[str]]`, that centralizes SD caption generation, configuration gating, and fallbacks when an `ImageAnalysis` is already available.  
  - Refactor `WorkflowOrchestrator.execute` and `WebImageService.analyze_and_caption` to:
    - Continue performing analysis where they need the full `ImageAnalysis` object.  
    - Call `ai_service.create_caption_pair_from_analysis(analysis, spec)` instead of using `CaptionGeneratorOpenAI` directly.  
  - Optionally, refactor `AIService.create_caption_pair` internally to delegate to a shared private helper to keep behavior identical between “from URL” and “from analysis” entrypoints.

### 4.2 Components & Responsibilities

- `publisher_v2.services.ai.AIService` — Becomes the single abstraction for SD caption generation:  
  - Keeps existing `create_caption` and `create_caption_pair` signatures.  
  - Adds `create_caption_pair_from_analysis` that:
    - Applies the same `sd_caption_enabled` and `sd_caption_single_call_enabled` logic.  
    - Uses the same `generate_with_sd` JSON contract and fallback-to-`generate` behavior.  
    - Executes caption generation under the `AsyncRateLimiter`.  
- `publisher_v2.core.workflow.WorkflowOrchestrator` — Delegates all SD caption work to `AIService`, no longer referencing `CaptionGeneratorOpenAI` directly.  
- `publisher_v2.web.service.WebImageService` — Delegates SD caption generation to `AIService` in the same way, preserving web-specific logging and sidecar-writing behavior.  
- Tests:
  - Existing SD caption tests validate output contracts and fallbacks; new tests ensure `AIService` methods are the only SD caption entrypoints used by orchestrator and web service.

### 4.3 Data & Contracts

- No changes to:
  - External JSON fields in preview, web responses, or sidecars.  
  - `CaptionGeneratorOpenAI.generate_with_sd` return structure (`{"caption": str, "sd_caption": str}`).  
- Internal contracts:
  - `AIService.create_caption_pair_from_analysis` returns `(caption, sd_caption_or_none)` and never raises for SD-specific errors without first attempting the caption-only fallback, mirroring `create_caption_pair`.  
  - Callers remain responsible for attaching `sd_caption` to `ImageAnalysis` for metadata building, and for writing sidecars via existing utilities.

### 4.4 Error Handling & Edge Cases

- If SD caption generation is disabled via config:
  - `create_caption_pair_from_analysis` runs `generate` only and returns `(caption, None)`.  
- If JSON decoding or SD-specific generation fails:
  - `AIService` logs the error (using existing event names) and falls back to caption-only `generate`, returning `(caption, None)`.  
- If caption-only generation fails:
  - `AIService` raises `AIServiceError` as it does today; callers (workflow/web) continue to handle this as a fatal AI error consistent with current behavior.  
- Rate limiting:
  - All SD caption requests go through `AsyncRateLimiter`; callers must not wrap SD caption calls in additional retry loops.

### 4.5 Security, Privacy, Compliance

- Prompts, models, and PG‑13 constraints remain as defined in the parent feature and `CaptionGeneratorOpenAI`; this change does not modify any prompt content or safety rules.  
- No new secrets or config fields are introduced; existing `OpenAIConfig` keys remain the only inputs.  
- Logging continues to redact prompt and response content, logging only metadata (e.g., timing, model, error type).

## 5. Detailed Flow

- Main success path (workflow):
  1. `WorkflowOrchestrator.execute` selects image, downloads content, and computes hashes as before.  
  2. It calls `ai_service.analyzer.analyze(temp_link)` to obtain `ImageAnalysis`.  
  3. It builds `CaptionSpec` as today based on platform configuration.  
  4. It calls `ai_service.create_caption_pair_from_analysis(analysis, spec)`:
     - Under the rate limiter, SD caption is generated via `generate_with_sd` when enabled.  
     - Fallback to `generate` is applied if SD generation is disabled or fails.  
  5. It receives `(caption, sd_caption_or_none)` and proceeds to sidecar writing and publishing unchanged.  
- Main success path (web analyze):
  1. `WebImageService.analyze_and_caption` validates the file and obtains a temp link.  
  2. It calls `ai_service.analyzer.analyze(temp_link)` to obtain `ImageAnalysis`.  
  3. It builds `CaptionSpec` from web configuration.  
  4. It calls `ai_service.create_caption_pair_from_analysis(analysis, spec)` and then attaches `sd_caption` to `analysis` when present for downstream metadata builders.  
  5. It writes sidecar and returns `AnalysisResponse` as before.  
- Edge cases:
  - SD caption disabled or failing: flows above still produce a normal `caption` and update sidecars/metadata consistently with “no SD caption” semantics.  

## 6. Testing Strategy (for this Change)

- Unit tests:
  - Add tests for `AIService.create_caption_pair_from_analysis` covering:
    - SD enabled vs. disabled.  
    - Single-call success returning both fields.  
    - SD failure and fallback to caption-only.  
  - Update or extend `test_ai_sd_generate.py` to exercise both URL-based and analysis-based entrypoints.  
- Integration tests:
  - `test_workflow_sd_integration.py`: assert that workflow results still include SD caption and sidecar contents under SD-enabled configurations, using mocks/spies to confirm `CaptionGeneratorOpenAI` is only called via `AIService`.  
  - `test_e2e_sd_caption.py`: ensure overall behavior (sidecar content, preview fields) remains unchanged.  
  - Web tests (`test_web_service.py`, `web_integration/test_web_endpoints.py`): verify that `/api/images/{filename}/analyze` still returns the same fields and that SD behavior is routed through `AIService`.  
- E2E / manual:
  - Optional manual run with real credentials to confirm no regressions in captions/sidecars while inspecting logs for new `AIService`-level events.

## 7. Risks & Alternatives

- Risks:
  - Refactoring call sites could inadvertently change logging patterns or error propagation — mitigated by keeping existing event names and ensuring tests assert on both behavior and logging where important.  
  - Introducing a new `AIService` API might be misused in future features — mitigated by keeping the interface narrow and well-documented, with `create_caption_pair` and `create_caption_pair_from_analysis` as the only sanctioned SD caption entrypoints.  
- Alternatives:
  - Force all flows to use `create_caption_pair(url_or_bytes, spec)` and drop separate analyzer calls — rejected to avoid redundant analysis and higher cost.  
  - Expose SD caption generation directly on `CaptionGeneratorOpenAI` only — rejected; it would keep rate limiting and policy decisions fragmented across call sites.

## 8. Work Plan (Scoped)

- Add `AIService.create_caption_pair_from_analysis(analysis, spec)` and refactor `create_caption_pair` to share internal SD caption generation logic where appropriate.  
- Update `WorkflowOrchestrator.execute` to call the new `AIService` helper instead of using `CaptionGeneratorOpenAI` directly for SD captions and fallbacks.  
- Update `WebImageService.analyze_and_caption` similarly to delegate to `AIService` for SD caption generation.  
- Adjust and extend unit and integration tests to assert that SD caption generation is only accessed via `AIService`, while keeping observable outputs and sidecar behavior unchanged.  
- Document the new `AIService` method and its intended use in internal developer docs or code comments.

## 9. Open Questions

- Should `AIService.create_caption_pair_from_analysis` also return the (potentially mutated) `ImageAnalysis` instance to allow future in-method enrichment? — Proposed answer: not needed for this change; callers already hold the analysis object.  
- Do we need explicit metrics at the `AIService` level for SD caption success/failure separate from existing logs? — Proposed answer: can be added later under the performance/telemetry feature set (Feature 007).  
- Are there any non-obvious call sites of `CaptionGeneratorOpenAI.generate_with_sd` that also need migration? — Proposed answer: confirm via repository-wide search during implementation; if found, standardize them on `AIService` as part of this change.


