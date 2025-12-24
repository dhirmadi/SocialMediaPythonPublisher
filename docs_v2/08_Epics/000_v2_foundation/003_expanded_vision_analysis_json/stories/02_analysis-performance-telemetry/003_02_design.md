<!-- docs_v2/08_Epics/08_04_ChangeRequests/003/001_analysis-performance-telemetry_design.md -->

# Analysis Performance & Telemetry — Change Design

**Feature ID:** 003  
**Change ID:** 003-001  
**Parent Feature:** Expanded Vision Analysis JSON  
**Design Version:** 1.0  
**Date:** 2025-11-20  
**Status:** Design Review  
**Author:** TODO (Architecture Team)  
**Linked Change Request:** docs_v2/08_Epics/08_04_ChangeRequests/003/001_analysis-performance-telemetry.md  
**Parent Feature Design:** docs_v2/08_Epics/08_02_Feature_Design/003_expanded-vision-analysis-json_design.md  

## 1. Summary

- Problem & context: The expanded vision analysis prompt adds more fields and tokens, but `VisionAnalyzerOpenAI` today does not enforce explicit token/latency bounds or emit standardized timing telemetry. This makes it harder to ensure we meet the NFRs and to diagnose regressions as prompts or models evolve.
- Goals: Bound analysis complexity via sane, testable defaults for `max_tokens` and prompt size; add structured timing (and optional token) logs around the analysis call; keep JSON fields, semantics, and preview behavior unchanged.
- Non-goals: Changing analysis fields or schema, altering publisher/storage behavior, or introducing a new monitoring stack; this change is limited to the analysis service and logging/metrics hooks.

## 2. Context & Assumptions

- Current behavior:
  - `AIService.create_caption[_pair]` acquires an `AsyncRateLimiter` and then calls `VisionAnalyzerOpenAI.analyze(url_or_bytes)`.
  - `VisionAnalyzerOpenAI.analyze` builds system/user messages, calls `AsyncOpenAI.chat.completions.create` with `response_format={"type": "json_object"}` and `temperature=0.4`, then parses JSON into `ImageAnalysis`.
  - There is no explicit `max_tokens` configured for the analysis response, and no structured timing logs specific to the analysis step; observability is largely implicit via generic logs/tests.
- Constraints from parent feature:
  - Must preserve all `ImageAnalysis` fields and semantics defined in `003_expanded-vision-analysis-json_design.md`.
  - Description length remains ≤ 30 words; safety fields and PG-13 tone are unchanged.
  - Rate limiting (`AsyncRateLimiter`) and tenacity-based retries must remain in place; no new blocking calls in the async path.
- Dependencies:
  - `AsyncOpenAI` client and OpenAI chat completions API.
  - `publisher_v2.utils.logging.log_json` for structured JSON logs.
  - Global NFRs in `docs_v2/06_NFRs/NFRS.md` (overall latency budgets) and any future cross-cutting perf/observability guidance.

## 3. Requirements

### 3.1 Functional Requirements

- **CR1:** `VisionAnalyzerOpenAI.analyze` must measure wall-clock latency for each OpenAI analysis call and emit a structured JSON log via `log_json` that includes at least: a correlation identifier, the analysis model name, and a `vision_analysis_ms` timing field.
- **CR2:** Analysis calls must configure explicit token-related limits (`max_tokens` and, where supported, `max_completion_tokens`) sized appropriately for the expanded JSON, while keeping behavior backward compatible.
- **CR3:** Telemetry logging must integrate cleanly with existing logging patterns: no secrets, compact fields, and reuse of existing correlation ID patterns where available.
- **CR4:** In CLI preview mode, it is permissible (but not required) to display a succinct “analysis completed in X ms” line based on the same measured timing, without altering existing preview content or formatting.

### 3.2 Non-Functional Requirements

- Latency:
  - Typical p95 analysis latency for representative images and configured model should be within a documented target (initially 1500 ms p95 as a working assumption, to be validated and refined via tests/measurements).
  - The change must not materially regress overall E2E latency NFRs (≤ 30s per post).
- Observability:
  - Logs must be structured JSON with stable field names (e.g., `event=\"vision_analysis\"`, `vision_analysis_ms`, `model`, `ok`, `error_type`).
  - Token limits and, where available, token usage (`prompt_tokens`, `completion_tokens`, `total_tokens`) should be trivially derivable from logs/metrics; explicit token logging is optional but preferred when exposed by the client.
- Security & privacy:
  - No image URLs, captions, or sensitive payloads are logged; only non-sensitive metadata (timings, model name, counts, booleans).
- Compatibility:
  - No changes to public CLI flags or config structure; any new tuning knobs must be optional and default to current behavior.

## 4. Architecture & Design (Delta)

### 4.1 Current vs. Proposed

- Current:
  - `VisionAnalyzerOpenAI.analyze` calls OpenAI without explicit token limits and returns `ImageAnalysis`; timing is not measured or logged at the analysis level.
  - Observability around analysis is implicit (e.g., generic error logs, test behavior), but there is no first-class analysis telemetry event.
- Proposed:
  - Wrap the OpenAI call in `analyze` with high-resolution timing (e.g., `time.perf_counter()`), capturing elapsed milliseconds.
  - Add a small telemetry block that emits a single structured log entry per call using `log_json`, including timing, model, and outcome (success/failure).
  - Pass explicit token limit parameters into `chat.completions.create` using conservative defaults suitable for the expanded JSON schema.

### 4.2 Components & Responsibilities

- `VisionAnalyzerOpenAI` — Add timing measurement and structured telemetry emission around the OpenAI call; configure explicit token limits.
- `publisher_v2.utils.logging.log_json` — Existing utility (unchanged) used to emit the new telemetry events.
- `AIService` — No functional change; continues to orchestrate analysis and caption generation behind the existing rate limiter.
- `utils.preview` — Optionally consume the measured analysis duration for human-friendly preview output, without changing existing analysis content.

### 4.3 Data & Contracts

- No changes to the `ImageAnalysis` data model or its JSON mapping.
- OpenAI request:
  - Add `max_tokens` (and, if available, `max_completion_tokens`) arguments sized for the existing strict JSON schema (e.g., low hundreds of tokens, not unbounded).
- Logging contract:
  - New structured log event (via `log_json`) with shape similar to:
    - `event`: `"vision_analysis"`
    - `model`: `<vision model name>`
    - `vision_analysis_ms`: `<float|int>`
    - `ok`: `true|false`
    - `error_type`: `<string or null>`
    - `correlation_id`: `<string or null>` (if a global correlation ID is available in logging context; otherwise optional/omitted).

### 4.4 Error Handling & Edge Cases

- On successful analysis:
  - Emit telemetry with `ok=true`, `error_type=null`, and the observed `vision_analysis_ms`.
- On exceptions inside `analyze` (including JSON decode fallback path):
  - Preserve existing behavior: tenacity retries, final `AIServiceError` wrapping.
  - Ensure a telemetry log is emitted once per outermost call with `ok=false` and a coarse `error_type` (e.g., `"json_decode_error"`, `"openai_error"`, `"unexpected_error"`), without leaking sensitive details.
- Edge cases:
  - Extremely slow responses: telemetry will reflect high `vision_analysis_ms`; higher-level NFR enforcement is test/ops driven.
  - Malformed or very large responses: existing fallback behavior remains; telemetry should still record timing and an `error_type`.

### 4.5 Security, Privacy, Compliance

- Logs must not contain:
  - Raw prompts, image URLs, captions, or analysis content.
  - API keys, access tokens, or other secrets.
- Telemetry fields are limited to timings, model identifiers, booleans, and coarse error categories, aligning with existing security guidelines.

## 5. Detailed Flow

- Main success path:
  1. `AIService.create_caption[_pair]` enters the rate limiter and calls `VisionAnalyzerOpenAI.analyze(url_or_bytes)`.
  2. `analyze` validates input (rejects raw bytes for now).
  3. `analyze` records `start = perf_counter()`, then calls `AsyncOpenAI.chat.completions.create(...)` with the existing messages plus explicit token limits.
  4. On response, `analyze` parses content into `ImageAnalysis` as today.
  5. `analyze` records `elapsed_ms = (perf_counter() - start) * 1000` and emits a `log_json` event with timing, model, and `ok=true`.
  6. Control returns to `AIService`, which continues as before (caption generation, etc.).
- Error path:
  1. Steps 1–3 as above.
  2. If the OpenAI call or JSON parsing raises, tenacity retries per current configuration.
  3. On final failure, before raising `AIServiceError`, capture elapsed time and emit a `log_json` event with `ok=false` and appropriate `error_type`.
  4. Caller behavior is unchanged: the orchestrator receives `AIServiceError` and handles it as today.

## 6. Testing Strategy (for this Change)

- Unit tests:
  - Add a test that patches `AsyncOpenAI.chat.completions.create` to a fast fake, invokes `VisionAnalyzerOpenAI.analyze`, and asserts that `log_json` is called with `event=\"vision_analysis\"` and a non-negative `vision_analysis_ms`.
  - Add a test that forces a JSON decode error (e.g., non-JSON content) and verifies that telemetry is still emitted with `ok=false` and an `error_type` indicating a parse issue.
- Integration tests:
  - Extend or add tests around `AIService.create_caption[_pair]` that assert analysis telemetry emission does not change functional outputs and that the analysis call still respects retries and error wrapping.
- Performance/observability tests:
  - Add a test that simulates a slower OpenAI call and asserts that `vision_analysis_ms` reflects the delay (within a tolerance).
  - Optionally add a lightweight benchmark/measurement harness under tests that can be run manually to validate p95 latency for representative inputs.

## 7. Risks & Alternatives

- Risks:
  - Misconfigured token limits could truncate valid JSON responses — mitigated by choosing conservative limits and validating against existing test fixtures.
  - Excessive logging volume if telemetry is too verbose — mitigated by emitting only one compact event per analysis call.
  - Timing measurements could be misleading in highly contended environments — mitigated by using them as guidance, not hard enforcement, and by correlating with higher-level monitoring.
- Alternatives considered:
  - Implementing a separate metrics backend (e.g., Prometheus) for analysis telemetry — rejected for now as overkill; structured logs are sufficient.
  - Measuring latency in the orchestrator instead of in `VisionAnalyzerOpenAI` — rejected to keep the measurement close to the OpenAI call and reusable across flows.

## 8. Work Plan (Scoped)

- Define and document default token limits and logging field names for `VisionAnalyzerOpenAI.analyze`.
- Implement timing measurement and structured telemetry logging in `VisionAnalyzerOpenAI.analyze`, ensuring no secrets or payload content are logged.
- Wire explicit token limits into the OpenAI analysis call with safe defaults.
- Add/extend unit and integration tests for telemetry behavior (success and error cases) and basic timing sanity checks.
- Optionally add a simple CLI/web-preview hook to show “analysis completed in X ms” without altering existing preview content.
- Validate behavior against sample images and confirm that existing tests (including those for expanded analysis JSON) remain green.

## 9. Open Questions

- What exact p95 latency target should we enforce or document for the configured vision model(s)? — Proposed answer: start with 1500 ms p95 as a working assumption aligned with overall NFRs; refine after collecting baseline measurements.
- Should token usage fields from OpenAI responses be explicitly logged (if/when exposed) or only inferred from higher-level metrics? — Proposed answer: start by logging them only when cheaply available and clearly non-sensitive; avoid increasing log volume unnecessarily.
- Do we need a dedicated CI step for analysis performance regression checks, or are periodic manual benchmarks sufficient? — Proposed answer: TODO; revisit once basic telemetry is in place and we have initial baseline data.


