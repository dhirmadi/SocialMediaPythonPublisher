# Expanded Vision Analysis JSON — Feature Design

## 1. Summary

Problem: The current image analysis returns minimal fields (description, mood, tags, nsfw, safety_labels), limiting preview fidelity and downstream Stable Diffusion (SD) prompt quality.  
Goals: Expand the analysis to include optional structured fields (subject, style, lighting, camera, clothing_or_accessories, aesthetic_terms, pose, composition, background, color_palette) while preserving strict JSON and backward compatibility. Surface present fields in preview.  
Non-goals: Change publisher behavior, modify caption generation logic (`sd_caption`), alter storage/archival or de-duplication flows, or switch AI providers.

## 2. Context & Assumptions

Current state:
- Vision analysis is performed by `AIService` using `VisionAnalyzerOpenAI` via OpenAI Chat Completions with `response_format={"type":"json_object"}`.
- `ImageAnalysis` model contains minimal fields; preview prints a concise summary.
- Rate limiting and retries are already in place (e.g., `AsyncRateLimiter`, tenacity).

Assumptions:
- The new fields are optional and may be missing; unknown values return `null` or an empty array.
- Description remains ≤ 30 words to preserve succinct previews.
- No changes to publishers or archival are required.

Dependencies:
- OpenAI Chat Completions (vision-capable model).
- Internal components: `WorkflowOrchestrator`, `AIService`, `VisionAnalyzerOpenAI`, `utils/preview`.

## 3. Requirements

Functional Requirements
1. Update the analysis prompt to request additional keys: subject, style, lighting, camera, clothing_or_accessories, aesthetic_terms (array), pose, composition, background, color_palette; retain existing keys.
2. Extend `ImageAnalysis` to include the new fields as optional; arrays default to empty list.
3. Parse model output strictly as JSON; coerce string fields to trimmed strings; set missing/unknown fields to `None` or empty array.
4. In `--preview` mode, print any present new fields with clear labels; omit absent ones.
5. Preserve existing behavior and outputs for current fields; do not break tests or flows.
6. Maintain description length constraint (≤ 30 words).
7. Continue to respect dry/preview semantics (no side effects).

Non-Functional Requirements
- Performance: Minimal token/latency increase; rate limiting preserved.
- Reliability: Retries on transient failures; robust JSON parsing and validation.
- Observability: Structured logs indicating presence/absence of optional fields and parse errors.
- Security/Privacy: No new PII; redact secrets; maintain PG-13 descriptive style in preview.
- Compatibility: Python 3.9–3.12; no new required config; backward compatible.

## 4. Architecture & Design

Proposed Architecture (diagram description)
- The `WorkflowOrchestrator` calls `AIService.analyze_image(...)`.
- `AIService` delegates to `VisionAnalyzerOpenAI.analyze(...)`.
- The analyzer sends a system+user message to OpenAI with the expanded strict-JSON request.
- Response JSON is parsed and mapped into an extended `ImageAnalysis` object.
- `utils/preview.print_vision_analysis(...)` prints available optional fields.
- Publishers and storage remain unchanged.

Components & Responsibilities
- `VisionAnalyzerOpenAI`: Build messages, call OpenAI, parse strict JSON, map to `ImageAnalysis`.
- `ImageAnalysis` model: Hold both existing and optional fields (all optional fields nullable).
- `utils/preview`: Conditionally print optional fields when present.
- `WorkflowOrchestrator`: Orchestrate flow; unchanged.

Data Model / Schemas (before/after)
- Before: `ImageAnalysis` had fields: description, mood, tags[], nsfw, safety_labels[], sd_caption? (unchanged).
- After (additions, all optional): subject, style, lighting, camera, clothing_or_accessories, aesthetic_terms[], pose, composition, background, color_palette.

API/Contracts (request/response; versioning)
- Request: OpenAI Chat Completions with `response_format={"type":"json_object"}`; system and user prompts expanded to list the additional keys explicitly and require null/empty for unknowns, no extra prose.
- Response: Strict JSON containing existing keys, plus any of the new optional keys.
- Versioning: Internal-only contract; tolerant parser ensures backward compatibility if OpenAI omits optional keys.

Error Handling & Retries
- Use existing tenacity-backed retries for transient API failures.
- On non-JSON or schema-violating responses, log structured error, retry with the same prompt (bounded), then raise a domain exception if still failing.
- Clamp description length post-parse if necessary.

Security, Privacy, Compliance
- Continue to redact secrets in logs.
- Maintain safety fields (nsfw, safety_labels) and PG-13 descriptive tone for preview output.
- No additional persistence of sensitive data.

## 5. Detailed Flow

Sequence of operations
1. Orchestrator selects image(s) and calls `AIService.analyze_image(image_ref)`.
2. `VisionAnalyzerOpenAI` builds `system` and `user` content including the expanded keys and description-length constraint.
3. OpenAI returns strict JSON; analyzer parses and normalizes fields:
   - Strings: `str(value).strip()` or `None` if missing.
   - Arrays: list of strings (empty list if missing).
4. Analyzer returns `ImageAnalysis` with optional fields set if present.
5. In preview mode, `utils/preview` prints existing fields and any present optional fields.
6. Downstream publishers ignore the new fields (unchanged).

Edge cases
- Model returns prose or invalid JSON: retry (bounded), then fail with actionable error.
- Missing fields: treat as `None` or empty list; preview omits absent.
- Overlong description: trim or instruct model to keep ≤ 30 words; enforce post-parse if needed.
- Rate-limiting or network errors: standard retries/backoff.

## 6. Rollout & Ops

Feature flags, Config
- Default: No new config required; optional fields printed automatically when present.
- Optional (future): A preview verbosity flag if output becomes too noisy.

Migration/Backfill plan
- None. No persisted schema changes or data migrations.

Monitoring, Logging, Dashboards, Alerts
- Logs: analysis success/failure, parse errors, count of present optional fields.
- Metrics: analysis success rate, parse failure count, average token usage (add TODO gauges).
- Dashboards/alerts: TODO — alert on sustained parse failures or API error spikes.

Capacity/Cost estimates
- Slight token cost increase due to expanded prompt and responses; expected to be within current budgets. Monitor P95/P99 latency.

## 7. Testing Strategy

Unit
- Parser normalization: `_opt_str`-style helper; string coercion and trimming.
- Mapping: Each optional field populated when present; omitted when missing.
- Description enforcement: word-count limit respected.

Integration
- `VisionAnalyzerOpenAI.analyze` end-to-end with a mocked OpenAI client returning the expanded JSON.
- `utils/preview` prints optional fields only when present.

E2E
- Pipeline run in `--preview` with sample images; verify outputs include optional fields when available and no side effects occur.

Performance
- Measure analysis time deltas versus baseline; ensure no material regressions.

Test Cases mapped to Acceptance Criteria
1. JSON includes existing keys; optional keys may be present — assert presence/absence handling.
2. Unknown details → null/empty — assert normalization.
3. Description ≤ 30 words — assert max length.
4. Preview prints available fields — assert conditional rendering.
5. Backward compatibility — legacy-only fields still parse and display.
6. Malformed output → retries then error — assert retry count and error type.

## 8. Risks & Alternatives

Risks with mitigations
- Increased token cost/latency — Keep prompts concise, temperature low; monitor; roll back if needed.
- Schema drift / non-strict JSON — Use `response_format`, explicit keys, retries, strict parser.
- Preview clutter — Print only present fields; consider optional verbosity flag later.

Alternatives considered
- Use a separate second-pass prompt to extract detailed fields — rejected due to added latency and cost.
- Store new fields in sidecar JSON — deferred; not required for this iteration.
- Gate behind a config flag — not necessary; optional printing keeps output clean.

## 9. Work Plan

Milestones, Tasks, Owners
- M1 Discovery/Design: finalize field list and prompt language; agree tests. Owner: TODO.
- M2 Implementation:
  - Update prompts in `VisionAnalyzerOpenAI`.
  - Extend `ImageAnalysis`; add parser normalization helper.
  - Map optional fields; update preview printing.
  - Add/adjust tests (unit, integration, e2e preview).
  - Add observability (logs/metrics).
  Owner: TODO.
- M3 Validation/Rollout:
  - Run preview on sample batch; verify outputs and performance.
  - Docs update under `docs_v2`.
  - Monitor metrics post-merge.
  Owner: TODO.

Definition of Done
- Optional fields available in `ImageAnalysis` and preview.
- All tests green; coverage for new logic and error paths.
- No regressions in CLI behavior or publishers.
- Docs updated; basic metrics/logs in place.

## 10. Appendices

Glossary
- SD: Stable Diffusion
- Optional field: A field that may be missing or null without causing errors.

References
- Feature Request: `docs_v2/08_Epics/08_01_Feature_Request/003_expanded-vision-analysis-json.md`
- Existing Design Example: `docs_v2/08_Epics/08_02_Feature_Design/001_captionfile_design.md`


