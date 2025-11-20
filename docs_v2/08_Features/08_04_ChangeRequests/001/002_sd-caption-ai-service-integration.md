<!-- docs_v2/08_Features/08_04_ChangeRequests/001/002_sd-caption-ai-service-integration.md -->

# SD Caption AI Service Integration — Change Request

**Feature ID:** 001  
**Change ID:** 001-002  
**Name:** sd-caption-ai-service-integration  
**Status:** Proposed  
**Date:** 2025-11-20  
**Author:** Architecture Team  
**Parent Feature Design:** docs_v2/08_Features/08_02_Feature_Design/001_captionfile_design.md  

## Summary
This change ensures that all Stable Diffusion caption generation flows go through the shared `AIService` abstraction instead of calling `CaptionGeneratorOpenAI` directly from multiple places.  
By centralizing SD caption generation in `AIService`, we unify rate limiting, retries, error handling, and configuration for both CLI and web paths while preserving the single-call `{caption, sd_caption}` behavior defined in the parent feature.  
The outward behavior of caption and sidecar generation remains the same, but the internal wiring becomes simpler and more robust.

## Problem Statement
The captionfile feature currently defines a single-call `generate_with_sd` path but allows callers (e.g., `WorkflowOrchestrator`, `WebImageService`) to interact directly with `CaptionGeneratorOpenAI`.  
This leads to duplicated logic and fragmented control of rate limiting and error-handling, and makes it harder to evolve SD caption behavior consistently across interfaces.  
Without a clear requirement to centralize SD caption calls in `AIService`, there is a risk of divergent behavior and subtle performance or reliability regressions.

## Goals
- Route all SD caption generation (including single-call `{caption, sd_caption}` paths) through `AIService` entrypoints.  
- Ensure rate limiting, retries, and error-handling policies for SD captions are defined and enforced in one place.  
- Keep public behavior and configuration semantics of the captionfile feature unchanged.

## Non-Goals
- Changing prompt wording, model selection, or the JSON structure of `{caption, sd_caption}` responses.  
- Altering when or how sidecars are written and archived.  
- Introducing new configuration options beyond what the parent feature already defines.

## Affected Feature & Context
- **Parent Feature:** Stable Diffusion Caption File  
- **Relevant Sections:**  
  - §4. Architecture & Design – `CaptionGeneratorOpenAI.generate_with_sd`, `AIService`, and `WorkflowOrchestrator`.  
  - §5. Detailed Flow – single-call caption + SD caption generation.  
  - §9. Work Plan – tasks related to `AIService` integration.  
- This change tightens the architecture by making `AIService` the canonical API for both caption and SD caption generation, which is then consumed by the workflow and web layers without bypassing it.

## User Stories
- As a maintainer, I want all SD caption generation to be routed through `AIService`, so that I can adjust rate limits and error handling in one place and know all callers are consistent.  
- As an operator, I want SD caption behavior to be identical between CLI and web paths, so that I can rely on the same quality and reliability regardless of how the system is invoked.  
- As a developer, I want a clear, documented interface for generating `{caption, sd_caption}`, so that adding new callers or refactoring existing ones is straightforward.

## Acceptance Criteria (BDD-style)
- Given any code path that needs both `caption` and `sd_caption`, when it is executed, then it must invoke a documented `AIService` method (e.g., `create_caption_pair` or equivalent) instead of calling `CaptionGeneratorOpenAI` directly.  
- Given SD caption generation is disabled or misconfigured, when a caller uses the `AIService` interface, then the behavior must fall back to the legacy caption-only path exactly as defined in the parent feature.  
- Given rate limiting or transient failures occur during SD caption generation, when those errors are raised, then retries and error logging must follow the policies defined in `AIService` and the parent feature.  
- Given tests for CLI and web flows, when they are run, then they must pass using the centralized `AIService` paths with no regressions in output fields or sidecar behavior.

## UX / UI Requirements
- No new UI elements are required; CLI and web behavior must remain functionally identical from a user perspective.  
- Any error or status messaging related to SD captions must stay consistent with the existing feature design (e.g., best-effort behavior and non-fatal failures).  
- If future UI elements surface SD caption status, they should rely on data produced by the centralized `AIService` path.

## Technical Notes & Constraints
- `AIService` must expose a clear method for single-call `{caption, sd_caption}` generation that wraps `generate_with_sd` and its fallbacks.  
- Call sites in `WorkflowOrchestrator`, `WebImageService`, or other components should be refactored to use `AIService` rather than instantiating or calling `CaptionGeneratorOpenAI` directly for SD captions.  
- Existing configuration flags (`sd_caption_enabled`, `sd_caption_single_call_enabled`, `sd_caption_model`, prompts) remain the single source of truth and must continue to be respected.  
- No changes may be made that violate existing retry, timeout, or PG-13 content constraints from the parent feature.

## Risks & Mitigations
- Refactoring multiple call sites could introduce regressions — Mitigation: add or update tests that cover both CLI and web paths, verifying that SD captions and sidecars are still produced correctly.  
- Centralizing logic might mask feature-specific nuances — Mitigation: ensure `AIService` remains thin and delegates feature-specific details (like sidecar building) back to the appropriate layers.  
- Misconfiguration of `AIService` could affect all callers — Mitigation: keep configuration backward-compatible and well-documented; consider conservative defaults.

## Open Questions
- Should `AIService` expose separate methods for caption-only vs. caption+SD, or a single flexible interface? — Proposed answer: maintain both a caption-only and a caption+SD method for clarity.  
- Do we need additional metrics at the `AIService` level specifically for SD captions? — Proposed answer: TODO; may be added in conjunction with broader telemetry work.  
- Are there any non-standard callers of `CaptionGeneratorOpenAI` outside the main workflow and web service that also need to be migrated? — Proposed answer: TODO; audit call sites during implementation.


