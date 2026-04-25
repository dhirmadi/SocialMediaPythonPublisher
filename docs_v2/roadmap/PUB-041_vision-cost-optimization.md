# PUB-041 — Vision Cost Optimization & Richer Caption Inputs

| Field | Value |
|-------|-------|
| **ID** | PUB-041 |
| **Category** | AI / Observability |
| **Priority** | P0 |
| **Effort** | M |
| **Status** | Not Started |
| **Dependencies** | PUB-025 (Done), PUB-034 (Done), PUB-039 (Done) |

---

## Problem

Every image analysis sends the **full-resolution original** to OpenAI's vision API with the default `detail: "high"` setting. For a typical 4000×6000 DSLR photo, this costs ~1105 image tokens per call (6 tiles × 170 + 85 base). Benchmarking on six representative images showed that **1024px resize + `detail: "low"` produces stable, usable vision JSON at ~85 fixed tokens** — a **~93% reduction** in vision token cost — with no degradation in caption or SD sidecar quality.

At the same time, the caption generation prompt only feeds `description`, `mood`, and `tags` from the vision analysis into the caption model. The full `ImageAnalysis` includes `lighting`, `composition`, `pose`, `aesthetic_terms`, `color_palette`, `style` — all paid for but unused in captions.

## Solution

Five-part improvement based on expert benchmarking:

1. **Default cheap vision path**: 1024px resize + `detail: "low"` for all analysis
2. **Configurable fallback**: full resolution + `detail: "high"` as quality escalation on JSON parse failure
3. **Richer caption prompts**: feed more of `ImageAnalysis` into caption generation
4. **Pipeline metrics**: structured log events for vision success, fallback usage, and token tracking
5. **Tenant-configurable settings**: vision quality in runtime config

---

## Parts

### Part A — Image Resize & Detail Control in `VisionAnalyzerOpenAI`

All changes happen **inside `VisionAnalyzerOpenAI.analyze()`** (`services/ai.py`) so both the workflow and web service paths benefit without caller changes.

**New constructor parameters** (from `OpenAIConfig`):

| Config field | Type | Default | Notes |
|-------------|------|---------|-------|
| `vision_max_dimension` | `int` | `1024` | Longest side in px. `0` = no resize (send original URL) |
| `vision_detail` | `str` | `"low"` | OpenAI `detail` parameter: `low`, `high`, `auto` |

**Flow when `vision_max_dimension > 0`**:

1. `analyze()` receives a presigned URL (existing callers unchanged)
2. Download the image bytes via `httpx` (async)
3. Resize using `Pillow`: longest side ≤ `vision_max_dimension`, preserve aspect ratio, `LANCZOS` resampling
4. If the image is already small enough, skip resize but still convert to JPEG for consistency
5. JPEG encode at quality 85
6. Build a base64 data URL: `data:image/jpeg;base64,{encoded}`
7. Send data URL to OpenAI with `image_url: {"url": data_url, "detail": vision_detail}`

**Flow when `vision_max_dimension == 0`** (legacy path):

1. Send the presigned URL directly to OpenAI with `image_url: {"url": url, "detail": vision_detail}`

**New helper function** in `utils/images.py`:

```python
def resize_image_bytes(data: bytes, max_dimension: int, quality: int = 85) -> bytes:
```

Returns JPEG bytes with longest side ≤ `max_dimension`. This is a sync function; `analyze()` calls it via `asyncio.to_thread()`.

### Part B — Quality Escalation Fallback

The fallback is a **quality escalation** — separate from the existing `@retry(stop=stop_after_attempt(3))` decorator which handles transient HTTP errors. The escalation fires when all 3 retries of the cheap path produce an unusable response (JSON decode failure after all retries exhausted).

**New constructor parameters** (from `OpenAIConfig`):

| Config field | Type | Default | Notes |
|-------------|------|---------|-------|
| `vision_fallback_enabled` | `bool` | `True` | Escalate to higher quality on parse failure |
| `vision_fallback_max_dimension` | `int` | `2048` | Fallback longest-side dimension |
| `vision_fallback_detail` | `str` | `"high"` | Fallback detail setting |

**Implementation**: Wrap the existing `analyze()` in a new public method (or restructure internally):

1. Call `_analyze_core(url, max_dim=config.vision_max_dimension, detail=config.vision_detail)`
2. If `AIServiceError` is raised **and** `vision_fallback_enabled`:
   - Log structured warning: `vision_fallback_triggered` (includes filename from URL if extractable, original error)
   - Call `_analyze_core(url, max_dim=config.vision_fallback_max_dimension, detail=config.vision_fallback_detail)`
3. If fallback also fails or fallback is disabled: raise `AIServiceError` (existing behavior)
4. Fallback adds **at most one** additional OpenAI vision call (the escalated attempt has its own 3 retries)

**Interaction with metering**: Both the cheap call's usage AND the fallback call's usage are returned (caller accumulates both into `UsageMeter`).

### Part C — Richer Caption Prompt Inputs

Today `generate`, `generate_with_sd`, and `_build_multi_prompt` only inject:

```
description='{analysis.description}', mood='{analysis.mood}', tags={analysis.tags}
```

**Add a new helper** `build_analysis_context(analysis: ImageAnalysis) -> str` that produces a bounded string containing available fields:

| Field | Source | Include when |
|-------|--------|-------------|
| `description` | `analysis.description` | Always (existing) |
| `mood` | `analysis.mood` | Always (existing) |
| `tags` | `analysis.tags` | Always (existing) |
| `lighting` | `analysis.lighting` | Non-None |
| `composition` | `analysis.composition` | Non-None |
| `pose` | `analysis.pose` | Non-None |
| `aesthetic_terms` | `analysis.aesthetic_terms` | Non-empty list |
| `color_palette` | `analysis.color_palette` | Non-None (this is `str \| None`) |
| `style` | `analysis.style` | Non-None |

**Excluded** (sensitive, verbose, or low-value for captions): `nsfw`, `safety_labels`, `camera`, `clothing_or_accessories`, `background`, `subject`, `sd_caption`.

**Token budget**: Truncate each string field to ≤50 chars and lists to first 10 items. Total additional context from the new fields should add ≤200 tokens (rough estimate: 4 chars/token).

**Call sites**: Replace the inline `description='...'` string construction in `generate()`, `generate_with_sd()`, and `_build_multi_prompt()` with `build_analysis_context(analysis)`.

### Part D — Pipeline Metrics

Extend structured logging with new events:

| Event name | Level | When | Extra fields |
|-----------|-------|------|-------------|
| `vision_analysis` | INFO | Already exists (line ~207) | Add: `detail`, `max_dimension`, `resized` (bool) |
| `vision_fallback_triggered` | WARNING | Fallback fires | `original_error`, `fallback_max_dimension`, `fallback_detail` |
| `vision_fallback_result` | INFO | Fallback completes | `ok` (bool), `vision_tokens` |

Token counts already flow through `AIUsage` → `UsageMeter` (PUB-034). No new metering calls needed — just richer structured logs.

### Part E — Config Model & Runtime Integration

**`OpenAIConfig`** (`config/schema.py`) — add 5 fields:

| Field | Type | Default |
|-------|------|---------|
| `vision_max_dimension` | `int` | `1024` |
| `vision_detail` | `str` | `"low"` |
| `vision_fallback_enabled` | `bool` | `True` |
| `vision_fallback_max_dimension` | `int` | `2048` |
| `vision_fallback_detail` | `str` | `"high"` |

`field_validator` on `vision_detail` and `vision_fallback_detail`: must be one of `{"low", "high", "auto"}`.

**`OrchestratorAI`** (`config/orchestrator_models.py`) — add corresponding optional fields.

**`_build_app_config_v2`** (`config/source.py`) — map the 5 fields from `cfg.ai.*` to `openai_cfg.*` (same pattern as existing AI field mapping).

**`VisionAnalyzerOpenAI.__init__`** (`services/ai.py`) — read the 5 new fields from `OpenAIConfig`.

**Standalone mode** (`config/loader.py`): `OPENAI_SETTINGS` JSON env var gains the 5 fields (optional, defaulting to cheap path).

---

## Acceptance Criteria

### Image Resize & Detail (Part A)

1. **AC-01**: When `vision_max_dimension=1024` and given a 4000×6000 image URL, `analyze()` downloads the image, resizes it so the longest side is 1024px (resulting in 683×1024), and sends the resized image as a `data:image/jpeg;base64,...` URL to OpenAI.
2. **AC-02**: The `detail` field in the `image_url` dict sent to OpenAI is set to the value of `vision_detail` from config (default `"low"`).
3. **AC-03**: When `vision_max_dimension=0`, `analyze()` sends the presigned URL directly to OpenAI (no download, no resize). The `detail` parameter is still applied.
4. **AC-04**: When the image is already smaller than `vision_max_dimension` (e.g., 800×600 with max=1024), no upscaling occurs, but the image is still re-encoded as JPEG and sent as data URL for consistent behavior.
5. **AC-05**: Aspect ratio is preserved during resize (`LANCZOS` resampling).
6. **AC-06**: `resize_image_bytes(data, max_dimension, quality=85)` in `utils/images.py` takes raw bytes, returns JPEG bytes with longest side ≤ `max_dimension`. Transparent PNGs are handled (converted to RGB before JPEG encode).

### Fallback (Part B)

7. **AC-07**: When `analyze()` raises `AIServiceError` (after all retries) and `vision_fallback_enabled=True`, a second analysis attempt is made using `vision_fallback_max_dimension` and `vision_fallback_detail`.
8. **AC-08**: A structured log warning `vision_fallback_triggered` is emitted when fallback fires, including the original error message.
9. **AC-09**: When fallback is disabled (`vision_fallback_enabled=False`) or the fallback attempt also fails, `AIServiceError` is raised to the caller.
10. **AC-10**: Fallback produces at most one additional OpenAI vision call chain (the fallback call has its own retry policy).
11. **AC-11**: Both the primary and fallback `AIUsage` are returned to the caller (if both fire, both token counts are available for metering).

### Richer Caption Inputs (Part C)

12. **AC-12**: `build_analysis_context(analysis)` produces a string containing `description`, `mood`, `tags` (always), plus `lighting`, `composition`, `pose`, `aesthetic_terms`, `color_palette`, `style` when non-None/non-empty.
13. **AC-13**: `None` analysis fields are omitted entirely (no `"lighting='None'"` in the output).
14. **AC-14**: Individual string fields are truncated to ≤50 characters; `aesthetic_terms` list is capped at 10 items.
15. **AC-15**: `nsfw`, `safety_labels`, `camera`, `clothing_or_accessories`, `background`, `subject` are never included in `build_analysis_context` output.
16. **AC-16**: `generate()`, `generate_with_sd()`, and `_build_multi_prompt()` all use `build_analysis_context(analysis)` instead of the inline `description='...'` construction.

### Config (Part E)

17. **AC-17**: `OpenAIConfig` has `vision_max_dimension: int = 1024`, `vision_detail: str = "low"`, `vision_fallback_enabled: bool = True`, `vision_fallback_max_dimension: int = 2048`, `vision_fallback_detail: str = "high"`.
18. **AC-18**: `vision_detail` and `vision_fallback_detail` validators reject values outside `{"low", "high", "auto"}`.
19. **AC-19**: `OrchestratorConfigSource` maps all 5 vision fields from the runtime payload into `OpenAIConfig`. Absent fields use defaults.
20. **AC-20**: `OPENAI_SETTINGS` JSON env var accepts the 5 vision fields in standalone mode.

### Backward Compatibility

21. **AC-21**: Setting `vision_max_dimension=0` and `vision_detail="high"` restores exact pre-PUB-041 behavior (presigned URL, no resize, no detail parameter change). Existing tests pass unchanged with this config.

---

## Out of Scope

- **Regression benchmark script**: Part E from the original proposal is deferred to a follow-up item. The manual benchmark tooling is valuable but is not part of the core cost optimization delivery.
- **CI-automated benchmark pipeline**
- **Orchestrator-side dashboard implementation** (publisher emits metrics; dashboards are orchestrator work)
- **A/B testing framework for vision quality**
- **`detail: "auto"` as default** (OpenAI's `auto` is unpredictable; explicit `low` preferred)

## Preview Mode

No special handling needed. Resize + low detail is a cost optimization that operates identically in preview mode. Preview mode remains side-effect free — the vision API call is the same, just cheaper.

## Research Evidence

Expert benchmarking on 6 representative images (DSLR fine-art/shibari photography):

| Configuration | Vision tokens (avg) | JSON success | Caption success | Notes |
|--------------|-------------------|--------------|-----------------|-------|
| Original + high (current) | ~1105 | 6/6 | 6/6 | Expensive baseline |
| 1024 + low | ~85 | 6/6 | 6/6 | **Recommended default** |
| 1024 + high | ~595 | Unstable | Partial | Many unusable JSON responses — avoid as default |
| 512 + low | ~85 | 6/6 | 6/6 | Works but less detail for complex compositions |

Key finding: `1024 + low` achieves ~93% vision token savings with identical downstream success rate. The `1024 + high` combination was unreliable and should not be default without retry/validation hardening.

## Coordination Notes

- **PUB-034 (Usage Metering)**: Both primary and fallback token counts flow through existing `AIUsage` → `UsageMeter` pipeline
- **PUB-039 (Feature Flags)**: Vision settings follow the same orchestrator → publisher config pattern
- **Pillow dependency**: Already present for thumbnail generation (PUB-024/PUB-031) and in `utils/images.py`

---

2026-04-25 — Spec hardened for Claude Code handoff
