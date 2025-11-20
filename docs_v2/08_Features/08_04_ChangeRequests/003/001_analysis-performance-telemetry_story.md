# Analysis Performance & Telemetry — Final Story

**Feature ID:** 003  
**Change ID:** 003-001  
**Status:** Shipped  
**Date Completed:** TODO  
**Code Branch / PR:** TODO  

## Summary
This change adds explicit performance and observability behavior around `VisionAnalyzerOpenAI` by bounding completion tokens for analysis calls and emitting structured timing telemetry, without altering the existing expanded analysis JSON schema or preview semantics.

## Goals
- Bound analysis complexity via explicit token and latency targets aligned with NFRs.
- Add structured timing logs for analysis calls to support monitoring and troubleshooting.
- Preserve all existing `ImageAnalysis` fields, semantics, and preview behavior.

## Non-Goals
- Changing the analysis JSON schema or the set of fields produced.
- Modifying publisher behavior, storage/archival flows, or sidecar formats.
- Introducing a new external metrics backend beyond what can be derived from structured logs.

## User Value
Operators and maintainers can now see how long analysis takes and verify that it remains within expected latency bounds as prompts or models evolve, making it easier to spot regressions and control token/cost growth while keeping the user-facing experience unchanged.

## Technical Overview
- Scope:
  - Focused on the Expanded Vision Analysis JSON feature, specifically `VisionAnalyzerOpenAI.analyze` and its surrounding observability.
- Core flow delta:
  - Previously, analysis called OpenAI without explicit token limits and no dedicated telemetry; now the call is wrapped with timing measurement and emits a single structured log event per invocation, while also supplying a conservative `max_tokens` limit (with graceful fallback for clients that do not support it).
- Key components:
  - `VisionAnalyzerOpenAI` now owns a logger (`publisher_v2.ai.vision`), a configurable `max_completion_tokens` default, and the telemetry emission.
  - `log_json` is reused to emit structured JSON logs with fields such as `event`, `model`, `vision_analysis_ms`, `ok`, and `error_type`.
- Flags / config:
  - No new required config fields were added; `vision_max_completion_tokens` is read via `getattr` for optional tuning while keeping defaults backward compatible.
- Data/state:
  - No changes to `ImageAnalysis` schema, sidecars, or persisted state; telemetry is purely log-based.

## Implementation Details
- `VisionAnalyzerOpenAI.__init__`:
  - Added a dedicated logger and a conservative `max_completion_tokens` default (512), with optional override via `OpenAIConfig`.
- `VisionAnalyzerOpenAI.analyze`:
  - Measures elapsed time using `time.perf_counter()` and records it as `vision_analysis_ms` in a `log_json` event.
  - Attempts to pass `max_tokens=self.max_completion_tokens` to `chat.completions.create`, with a TypeError fallback path that retries the call without `max_tokens` for older clients or test doubles.
  - Retains the existing JSON parsing and fallback behavior, now also tracking a coarse `error_type` (`json_decode_error` vs. generic `openai_error`) in telemetry.
- Tests:
  - New tests (`test_ai_vision_analysis_telemetry.py`) validate that telemetry logs are emitted on both success and JSON-fallback paths, that `vision_analysis_ms` is non-negative, and that the model and `event` fields are correctly set.
  - Existing analyzer error/expanded-field tests were kept green by the `max_tokens` fallback behavior.
- Performance / reliability:
  - The change adds a small constant overhead for timing and logging, but this is negligible relative to network and model latency; retries remain bounded via tenacity.
- Security / privacy:
  - Telemetry logs avoid recording prompts, image URLs, captions, or other sensitive payloads, logging only model name, timings, and coarse error categories.

## Testing
- Unit tests:
  - Validate that `VisionAnalyzerOpenAI.analyze` logs a `vision_analysis` event with `vision_analysis_ms >= 0` on success.
  - Validate that the JSON-fallback path still logs telemetry and returns a valid `ImageAnalysis`.
- Integration tests:
  - Existing AI analyzer error-path and expanded-field tests validate compatibility with the new telemetry and token limit behavior.
- E2E / manual checks:
  - Running the existing preview and end-to-end flows confirms that analysis outputs and sidecar behavior remain unchanged while logs now include timing events.

## Rollout Notes
- Flags:
  - No new feature flags were introduced; telemetry is always on but minimal.
- Monitoring / logs:
  - Operators can filter logs by `event="vision_analysis"` to inspect analysis latency and error patterns; p95 latency checks can be layered on top of these logs.
- Backout strategy:
  - If necessary, revert the `VisionAnalyzerOpenAI.analyze` telemetry changes or reduce log volume by adjusting log level or removing the timing event.

## Artifacts
- Change Request: docs_v2/08_Features/08_04_ChangeRequests/003/001_analysis-performance-telemetry.md
- Change Design: docs_v2/08_Features/08_04_ChangeRequests/003/001_analysis-performance-telemetry_design.md
- Change Plan: docs_v2/08_Features/08_04_ChangeRequests/003/001_analysis-performance-telemetry_plan.yaml
- Parent Feature Design: docs_v2/08_Features/08_02_Feature_Design/003_expanded-vision-analysis-json_design.md
- PR: TODO

## Final Notes
- Future work could add sampling or explicit token-usage logging once usage fields are standardized across clients, and potentially a lightweight CI/perf check keyed off `vision_analysis_ms` if regressions become a concern.


