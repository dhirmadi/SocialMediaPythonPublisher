<!-- docs_v2/08_Features/08_04_ChangeRequests/003/001_analysis-performance-telemetry.md -->

# Analysis Performance & Telemetry — Change Request

**Feature ID:** 003  
**Change ID:** 003-001  
**Name:** analysis-performance-telemetry  
**Status:** Proposed  
**Date:** 2025-11-20  
**Author:** Architecture Team  
**Parent Feature Design:** docs_v2/08_Features/08_02_Feature_Design/003_expanded-vision-analysis-json_design.md  

## Summary
This change tightens the performance and observability characteristics of the Expanded Vision Analysis JSON feature.  
It introduces explicit token and latency constraints for `VisionAnalyzerOpenAI`, as well as structured timing logs and metrics hooks, so that analysis remains fast and predictable as fields expand.  
The change preserves all existing JSON fields and semantics while adding clear, testable non-functional behavior.

## Problem Statement
The expanded analysis prompt adds more fields and tokens, but the design does not currently define concrete boundaries for token usage or latency.  
There is also no standardized, feature-level requirement for timing logs or metrics that would allow operators to verify compliance with NFRs or detect regressions.  
Without these, analysis latency can drift over time and performance issues become hard to diagnose.

## Goals
- Bound analysis complexity via explicit token and latency targets aligned with overall NFRs.  
- Add structured timing logs and simple metric hooks for the analysis stage to support monitoring and troubleshooting.  
- Keep the behavior of all existing fields and preview output unchanged while adding these performance-related guarantees.

## Non-Goals
- Changing the set of analysis fields, their names, or their JSON semantics.  
- Introducing new external monitoring systems or dashboards beyond what can be derived from existing logs/metrics.  
- Modifying publisher behavior or storage/archival logic.

## Affected Feature & Context
- **Parent Feature:** Expanded Vision Analysis JSON  
- **Relevant Sections:**  
  - §3. Requirements – functional and non-functional requirements for analysis fields.  
  - §4. Architecture & Design – `VisionAnalyzerOpenAI` and `ImageAnalysis`.  
  - §6. Rollout & Ops – monitoring, logging, and performance considerations.  
- This change refines the non-functional aspects of the existing design by specifying maximum token usage, target latency ranges, and mandatory timing logs for the analysis stage, without altering the structure of the response JSON.  
- It applies the cross-cutting telemetry pattern defined in `docs_v2/08_Features/08_01_Feature_Request/007_cross-cutting-performance-observability.md` specifically to the analysis component.

## User Stories
- As an operator, I want analysis timing and token usage to be bounded and visible in logs, so that I can ensure we meet our latency and cost targets.  
- As a maintainer, I want clear tests and requirements around analysis performance, so that future prompt or model changes cannot silently degrade response times.  
- As a developer, I want a simple way to correlate slow requests with the analysis step, so that I can quickly identify whether OpenAI calls are the bottleneck.

## Acceptance Criteria (BDD-style)
- Given an image is analyzed via `VisionAnalyzerOpenAI`, when the call completes successfully, then the logs must include a structured timing field (e.g., `vision_analysis_ms`) and a correlation ID.  
- Given normal operation and representative inputs, when measuring a sample of analysis calls, then p95 latency must remain within the bounds defined in the NFRs (or documented in this change) for the configured model.  
- Given analysis responses of typical size, when prompts and models are configured according to the design, then `max_tokens` and prompt lengths must prevent unbounded growth in token usage.  
- Given a malformed or extremely large response, when parsing into `ImageAnalysis`, then the system must still enforce description length limits and log any parsing/runtime anomalies without breaking existing behavior.

## UX / UI Requirements
- In CLI preview mode, no additional verbose output is required, but it is acceptable to optionally display a brief “analysis completed in X ms” line if desired.  
- The web UI does not need new UI elements for this change; performance telemetry is primarily surfaced via logs and any existing admin tools that read them.  
- Any future exposure of analysis timings to end users must remain minimal and non-intrusive.

## Technical Notes & Constraints
- `VisionAnalyzerOpenAI.analyze` should explicitly configure `max_tokens` and keep prompts concise while still requesting all fields defined in the parent feature.  
- Timing should be measured around the OpenAI call and recorded through the existing `utils.logging.log_json` mechanism with consistent field names.  
- Existing retry and error-handling behavior (via tenacity and `AIServiceError`) must remain intact.  
- No changes may be made that break compatibility with Python 3.9–3.12 or alter dry/preview semantics.  
- Any additional metrics hooks should be optional and derivable from logs if a full metrics backend is not present.  
- This change is additive and preserves existing externally visible behavior; defaults must continue to produce the same analysis outputs and preview formatting.

## Risks & Mitigations
- Overly strict latency targets might be unattainable for some models or network conditions — Mitigation: express targets as “typical p95” ranges and verify against real measurements before finalizing; allow configuration per model.  
- Additional logging could become noisy — Mitigation: keep timing fields compact and structured, and reuse existing logger categories; avoid duplicating messages.  
- Changes to prompts or `max_tokens` might subtly alter model behavior — Mitigation: update and run existing tests and snapshots to ensure JSON shape and content quality remain within expected bounds.

## Open Questions
- What exact p95 latency target should be recorded for the expanded analysis on our chosen OpenAI model(s)? — Proposed answer: align with existing NFRs and refine after baseline measurements.  
- Should token usage (prompt + completion) be explicitly logged per request or only sampled? — Proposed answer: start with optional logging where available; add sampling if volume becomes high.  
- Do we need a dedicated CI check for analysis performance, or is manual periodic benchmarking sufficient? — Proposed answer: TODO; evaluate after initial instrumentation is in place.


