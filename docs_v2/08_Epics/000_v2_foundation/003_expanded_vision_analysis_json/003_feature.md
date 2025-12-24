<!-- docs_v2/08_Epics/08_01_Feature_Request/003_expanded-vision-analysis-json.md -->

# Expanded Vision Analysis JSON

**ID:** 003  
**Name:** expanded-vision-analysis-json  
**Status:** Implemented  
**Date:** 2025-11-09  
**Author:** Evert  

## Summary
Expand the image analysis prompt to return a richer, structured JSON suitable for downstream captioning and Stable Diffusion (SD) prompt generation. Add optional fields (e.g., subject, style, lighting, camera) to the analysis model and surface them in preview without breaking existing behavior. Maintain strict-JSON responses and concise descriptions to keep outputs reliable and readable.

## Problem Statement
The current vision analysis returns minimal fields (description, mood, tags, nsfw, safety_labels), which limits preview detail and SD prompt quality. Operators and creators need richer, consistent structure (subject, style, lighting, camera, pose, composition, etc.) to quickly gauge content and generate better captions/prompts. We must enhance the analysis while preserving backward compatibility and the strict-JSON contract.

## Goals
- Expand the analysis prompt to request additional structured fields.
- Parse new fields into the analysis model as optional attributes.
- Optionally display the new fields in `--preview` without changing current flows.

## Non-Goals
- Changing publisher behavior or delivery logic.  
- Modifying caption generation logic or `sd_caption` behavior.  
- Altering storage/archival or de-duplication flows.  
- Switching AI providers or overhauling configuration.

## Users & Stakeholders
- Primary users: Operators running the pipeline; creators reviewing previews.  
- Stakeholders: AI service maintainers; platform publisher maintainers.

## User Stories
- As an operator, I want richer analysis fields so I can validate content quality quickly.  
- As a creator, I want detailed structure (subject, style, lighting, pose) so I can craft better SD prompts.  
- As a maintainer, I want optional fields and strict JSON so existing flows remain stable.

## Acceptance Criteria (BDD-style)
- Given an input image, when analysis runs, then the JSON includes the existing keys and may additionally include: subject, style, lighting, camera, clothing_or_accessories, aesthetic_terms (array), pose, composition, background, color_palette.  
- Given any unknown/unavailable detail, when analysis is returned, then the corresponding value is null (or empty array where applicable).  
- Given the description constraint, when analysis is returned, then description is ≤ 30 words.  
- Given a successful parse, when `--preview` is used, then available new fields are printed with clear labels and omitted if absent.  
- Given the new fields are optional, when the feature is deployed, then existing tests and flows continue to function unchanged.  
- Given malformed model output, when parsing occurs, then strict error handling and retries are applied per existing patterns (no silent failures).

## UX / Content Requirements
- Preview prints additional fields only if present, with readable labels and consistent ordering.  
- Maintain existing preview formatting and keep outputs concise.  
- Localization/Accessibility: N/A (CLI output only).

## Technical Constraints & Assumptions
- Python 3.9–3.12; async OpenAI client with rate limiting and `response_format={"type":"json_object"}`.  
- Integrate within `AIService` using `VisionAnalyzerOpenAI`; no publisher logic changes.  
- Backward-compatible: new model fields are optional; no required config changes.  
- Maintain temperature ~0.4 and strict JSON instructions to reduce hallucinations.

## Dependencies & Integrations
- OpenAI Chat Completions (vision).  
- Internal: `AIService`, `VisionAnalyzerOpenAI`, `utils/preview`, `WorkflowOrchestrator`.  
- No contract changes with external publishers.

## Data Model / Schema
- Extend `ImageAnalysis` with optional fields: subject, style, lighting, camera, clothing_or_accessories, aesthetic_terms (array), pose, composition, background, color_palette.  
- Preserve existing fields and their semantics; `sd_caption` unchanged.  
- Parsing: Coerce strings to trimmed text; arrays to lists of strings; null when unknown.  
- Persistence: No new storage; preview-only exposure (sidecars unchanged in this request).

## Security / Privacy / Compliance
- Maintain safety labeling and NSFW detection as-is.  
- Continue to redact secrets in logs.  
- Ensure outputs remain PG-13 descriptive style for preview.

## Performance & SLOs
- Minor token usage increase; rate limiting unchanged.  
- Target: No material regression in end-to-end batch latency (TODO: quantify P95/P99).  
- Retries remain bounded with tenacity backoff.

## Observability
- Metrics: analysis success rate, parse success/failure count, average token usage (TODO).  
- Logs & events: structured logs for present/missing optional fields and parse issues.  
- Dashboards/alerts: TODO.

## Risks & Mitigations
- Increased token cost/latency — Mitigation: concise prompts, keep temperature low, strict JSON.  
- JSON schema drift from model — Mitigation: explicit keys list, `response_format`, robust parsing with retries.  
- Preview noise from excessive fields — Mitigation: print only present fields with succinct labels.

## Open Questions
- Should we gate preview printing of new fields behind a config flag? — Proposed answer: Not required; optional fields printed only if present keeps output clean.  
- Should we store new fields in sidecar JSON? — Proposed answer: Not in this request; consider a follow-up if needed.  
- Any platform-specific consumers for new fields? — Proposed answer: None initially; publishers remain unchanged.

## Milestones
- M1: Discovery/Design — Updated prompt spec, model field list, test plan.  
- M2: Implementation — Prompt update, model extension, parser update, preview mapping, tests added.  
- M3: Validation/Rollout — Tests green, dry/preview runs validated, documentation updated.

## Definition of Done
- New optional fields parsed and accessible; existing behavior unchanged.  
- Preview displays available fields; omits absent ones.  
- All tests pass; new tests cover parsing and preview output.  
- Documentation updated; observability hooks in place for parse outcomes.  
- No regressions in CLI behavior or platform publishing.

## Appendix: Source Synopsis
- Current analysis prompt returns minimal fields; strict JSON enforced.  
- Proposal adds structured keys (subject, style, lighting, camera, clothing/accessories, aesthetic_terms, pose, composition, background, color_palette).  
- Changes are backward-compatible: optional model fields, strict JSON, concise description.  
- Optional preview printing of new fields; no publisher or storage changes required.


