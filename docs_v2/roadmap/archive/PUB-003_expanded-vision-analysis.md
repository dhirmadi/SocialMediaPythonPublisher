# PUB-003: Expanded Vision Analysis JSON

| Field | Value |
|-------|-------|
| **ID** | PUB-003 |
| **Category** | AI |
| **Priority** | INF |
| **Effort** | M |
| **Status** | Done |
| **Dependencies** | — |

## Problem

The current vision analysis returns minimal fields (description, mood, tags, nsfw, safety_labels), which limits preview detail and SD prompt quality. Operators and creators need richer, consistent structure (subject, style, lighting, camera, pose, composition, etc.) to quickly gauge content and generate better captions/prompts. The enhancement must preserve backward compatibility and the strict-JSON contract.

## Desired Outcome

Expand the analysis prompt to return a richer, structured JSON with optional fields. Parse new fields into the analysis model as optional attributes. Display new fields in `--preview` when present. Maintain strict-JSON responses and concise descriptions for reliable, readable outputs.

## Scope

- New optional fields: subject, style, lighting, camera, clothing_or_accessories, aesthetic_terms (array), pose, composition, background, color_palette
- Extend `ImageAnalysis` model; preserve existing fields and semantics
- Preview prints additional fields only if present; omit absent ones
- Description constraint: ≤ 30 words
- No publisher, storage, or caption logic changes

## Acceptance Criteria

- AC1: Given an input image, when analysis runs, then the JSON includes existing keys and may additionally include: subject, style, lighting, camera, clothing_or_accessories, aesthetic_terms (array), pose, composition, background, color_palette
- AC2: Given any unknown/unavailable detail, when analysis is returned, then the corresponding value is null (or empty array where applicable)
- AC3: Given the description constraint, when analysis is returned, then description is ≤ 30 words
- AC4: Given a successful parse, when `--preview` is used, then available new fields are printed with clear labels and omitted if absent
- AC5: Given the new fields are optional, when the feature is deployed, then existing tests and flows continue to function unchanged
- AC6: Given malformed model output, when parsing occurs, then strict error handling and retries are applied per existing patterns (no silent failures)

## Implementation Notes

- Integrate within `AIService` using `VisionAnalyzerOpenAI`
- `response_format={"type":"json_object"}`; temperature ~0.4
- Coerce strings to trimmed text; arrays to lists of strings; null when unknown
- Stories: implementation, analysis-performance-telemetry, preview-verbosity-controls

## Related

- [Original feature doc](../../08_Epics/000_v2_foundation/003_expanded_vision_analysis_json/003_feature.md) — full historical detail
