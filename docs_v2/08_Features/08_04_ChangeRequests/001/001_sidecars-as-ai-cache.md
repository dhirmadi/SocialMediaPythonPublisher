<!-- docs_v2/08_Features/08_04_ChangeRequests/001/001_sidecars-as-ai-cache.md -->

# Sidecars as AI Cache — Change Request

**Feature ID:** 001  
**Change ID:** 001-001  
**Name:** sidecars-as-ai-cache  
**Status:** Shipped  
**Date:** 2025-11-20  
**Author:** Architecture Team  
**Parent Feature Design:** docs_v2/08_Features/08_02_Feature_Design/001_captionfile_design.md  

## Summary
This change extends the Stable Diffusion caption file feature so that existing `.txt` sidecars can be used as a cache for AI analysis and captions, especially in the web interface.  
Instead of always recomputing analysis and captions via OpenAI, callers may reconstruct responses from the sidecar when it is present and valid, with an explicit mechanism to force a refresh.  
This reduces latency and cost while preserving all existing sidecar structure and semantics defined in the parent feature.

## Problem Statement
Today, the system always calls OpenAI to analyze and caption an image, even if a complete, structured sidecar has already been written.  
This leads to unnecessary latency and cost, particularly when browsing or re-analyzing images in the web interface or future preview flows.  
There is no documented, supported way to treat the `.txt` sidecar as a source of truth for analysis/caption data, so behavior and expectations are unclear.

## Goals
- Allow supported callers (starting with the web interface) to reconstruct analysis and captions from existing sidecars without hitting OpenAI.
- Preserve the sidecar format and semantics from the parent feature while formally designating it as a cacheable source of analysis/caption data.
- Provide a clear mechanism to bypass the cache and regenerate analysis/captions when desired.

## Non-Goals
- Changing the on-disk sidecar format or adding new required fields.
- Introducing new persistent stores beyond Dropbox sidecars and existing state files.
- Modifying publisher behavior or the core workflow’s archive semantics.

## Affected Feature & Context
- **Parent Feature:** Stable Diffusion Caption File  
- **Relevant Sections:**  
  - §3. Requirements – sidecar file creation and archive behavior.  
  - §4. Architecture & Design – `DropboxStorage.write_sidecar_text`, `WorkflowOrchestrator` integration.  
  - §5. Detailed Flow – sidecar creation and usage in preview.  
- This change formalizes sidecars as a reusable cache layer: components like `WebImageService` (and potential future CLI preview flows) may read and parse existing sidecars to answer analysis/caption requests without recomputing via OpenAI, while still relying on the parent feature’s existing creation and archive logic.  
- It serves as the canonical definition of “sidecars as AI cache” that other change requests (e.g., web performance sidecar cache) reference and apply in their respective layers.

## User Stories
- As an admin using the web UI, I want previously processed images to load captions and SD prompts instantly from their existing sidecars, so that I am not blocked by repeated AI calls when browsing.  
- As an operator, I want the system to treat sidecars as a safe cache of analysis and caption data, so that I can reduce OpenAI usage and improve responsiveness without changing my Dropbox structure.  
- As a maintainer, I want a clear API and behavior for when sidecars are reused versus when fresh analysis/captions are generated, so that I can implement and test caching logic confidently.

## Acceptance Criteria (BDD-style)
- Given an image that already has a valid sidecar written according to Feature 001, when a supported caller requests analysis/caption data without forcing a refresh, then the system returns fields reconstructed from the sidecar without calling OpenAI.  
- Given an image with no sidecar or an unreadable/invalid sidecar, when a supported caller requests analysis/caption data, then the system falls back to the existing OpenAI-based analysis and caption generation and writes/overwrites a correct sidecar.  
- Given any image (with or without an existing sidecar), when a caller explicitly requests a forced refresh, then the system performs a fresh OpenAI analysis and caption/SD-caption generation and writes a new sidecar, overriding previous cache contents.  
- Given that sidecar reuse is enabled, when a sidecar is reused to satisfy a request, then logs clearly indicate that cached data was used instead of a new OpenAI call.

## UX / UI Requirements
- Web UI behavior must clearly reflect when analysis/caption data is coming from cache versus from a fresh AI run (e.g., via subtle status text or timestamps), without adding clutter.  
- If a force-refresh action is exposed in the UI (e.g., a “Re-analyze” button), it must be clearly labeled, accessible, and only available to authorized/admin users.  
- No changes are required to CLI output formatting, aside from any optional status text indicating cache use in future preview flows.

## Technical Notes & Constraints
- The sidecar parser (`publisher_v2.web.sidecar_parser` or equivalent utility) must remain backward compatible with the sidecar format defined in Feature 001.  
- Cache behavior must be implemented as an additive layer on top of existing sidecar creation and archive logic; it must not change when and how sidecars are written or moved.  
- Callers must have a documented way (e.g., parameter or config) to choose between “reuse sidecar if present” and “force refresh,” with safe defaults.  
- No new persistent stores may be introduced; Dropbox and the existing filesystem-based state remain the only sources of truth.  
- Rate limiting and retry behavior for OpenAI calls remain governed by `AIService` and its `AsyncRateLimiter`.

## Risks & Mitigations
- Sidecar format drift or malformed sidecars could cause incorrect or partial data to be treated as authoritative — Mitigation: keep parsing robust and defensive, log parse errors, and automatically fall back to fresh analysis/caption generation when sidecars are invalid.  
- Users might be confused about when data is refreshed — Mitigation: expose a clear, intentional force-refresh pathway in APIs (and optionally UI), and document cache behavior in feature docs.  
- Hidden bugs could be masked by cached data — Mitigation: add tests that exercise both cached and non-cached paths, and ensure logging distinguishes them clearly.

## Open Questions
- Should sidecar reuse be enabled by default for all callers, or only for the web interface initially? — Proposed answer: Start with web only, then expand once behavior is validated.  
- How should force-refresh be exposed at the API level (query parameter, separate endpoint, or request body flag)? — Proposed answer: Prefer a simple query parameter (e.g., `?force_refresh=true`) for analyze-style endpoints.  
- Should any additional metadata (e.g., last AI model version) be considered when deciding whether to reuse or refresh sidecars? — Proposed answer: TODO; may be addressed in a later change request if needed.



