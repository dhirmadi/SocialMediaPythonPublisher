# PUB-026: AI Alt Text Generation

| Field | Value |
|-------|-------|
| **ID** | PUB-026 |
| **Category** | AI |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Not Started |
| **Dependencies** | PUB-039 (Done — `alt_text_enabled` flag already wired) |

## Problem

Published images have no alt text. Bluesky requires an `alt` field on embedded images (`app.bsky.embed.images`), Mastodon's media API has a `description` field, and the Fediverse community strongly expects alt text. Accessibility regulations increasingly require it. Our vision analysis already produces a rich structured description of every image (subject, lighting, composition, mood), but none of this is surfaced as alt text. We are sitting on the data and not using it.

## Solution

Add `alt_text` as a new field in the vision analysis prompt and `ImageAnalysis` dataclass. The field is always generated (negligible token cost — one short string in an existing API call) but only **consumed downstream** when `features.alt_text_enabled` is `True`. This avoids conditional prompt mutation while keeping the feature gateable.

Alt text flows through the publisher context dict so any publisher can consume it. Bluesky (PUB-027) and Mastodon (PUB-030) will wire it into their platform APIs when implemented.

---

## Parts

### Part A — Vision Prompt & Model Extension

**Extend the vision prompt** to request an `alt_text` field:

- Add `alt_text` to the key list in `_DEFAULT_VISION_SYSTEM_PROMPT` and `_DEFAULT_VISION_USER_PROMPT` (`services/ai.py`)
- Add `alt_text` to the vision section of `ai_prompts.yaml` (`config/static/ai_prompts.yaml`)
- Prompt constraint: `alt_text: string (≤125 characters, plain descriptive sentence for screen readers, no hashtags, no promotional language, no mood/interpretation — focus on what is visually depicted)`

**Extend `ImageAnalysis`** (`core/models.py`):

```python
alt_text: str | None = None
```

**Extend the parser** in `VisionAnalyzerOpenAI.analyze()` (`services/ai.py`):

```python
alt_text=self._opt_str(data.get("alt_text")),
```

Also add `"alt_text": None` to the JSON decode error fallback dict.

### Part B — Publisher Context

**Extend the workflow context** (`core/workflow.py`, line ~447):

When `features.alt_text_enabled` is `True` and `analysis.alt_text` is non-None, add `"alt_text"` to the context dict passed to publishers:

```python
context = {"analysis_tags": analysis.tags} if analysis else None
if analysis and config.features.alt_text_enabled and analysis.alt_text:
    context = context or {}
    context["alt_text"] = analysis.alt_text
```

No publisher changes needed now — current publishers (Telegram, Email) ignore unknown context keys. Bluesky (PUB-027) and Mastodon (PUB-030) will consume `context["alt_text"]` when they are implemented.

### Part C — Sidecar Metadata

**Extend `build_metadata_phase2`** (`utils/captions.py`):

When `alt_text` is present on the analysis, include it in the sidecar metadata dict:

```python
if getattr(analysis, "alt_text", None):
    meta["alt_text"] = analysis.alt_text
```

This is gated by the existing `config.captionfile.extended_metadata_enabled` flag (which controls whether Phase 2 metadata runs at all).

### Part D — Web UI & Preview

**Extend `AnalysisResponse`** (`web/models.py`):

```python
alt_text: str | None = None
```

**Wire in `analyze_and_caption`** (`web/service.py`):

Populate `alt_text` from the `ImageAnalysis` result when `features.alt_text_enabled` is `True`.

**Extend CLI preview** (`utils/preview.py`):

Add `alt_text` display in `print_vision_analysis()` after the existing optional fields:

```python
alt_text = getattr(analysis, "alt_text", None)
if alt_text:
    print(f"  Alt text:    {alt_text}")
```

---

## Acceptance Criteria

### Vision & Model (Part A)

1. **AC-01**: `ImageAnalysis` has field `alt_text: str | None` defaulting to `None`. Existing code that constructs `ImageAnalysis` without `alt_text` is unaffected.
2. **AC-02**: The default vision system prompt and user prompt include `alt_text` in the key list with the constraint: string, ≤125 characters, plain descriptive sentence for screen readers.
3. **AC-03**: `VisionAnalyzerOpenAI.analyze()` parses `alt_text` from the OpenAI JSON response via `_opt_str(data.get("alt_text"))`.
4. **AC-04**: When OpenAI returns a JSON decode error, the fallback dict includes `"alt_text": None` (no crash).
5. **AC-05**: When OpenAI omits `alt_text` from its response (key missing), `analysis.alt_text` is `None` (graceful degradation, not an error).

### Publisher Context (Part B)

6. **AC-06**: When `features.alt_text_enabled=True` and `analysis.alt_text` is non-None, the workflow context dict includes `{"alt_text": "..."}`.
7. **AC-07**: When `features.alt_text_enabled=False`, the context dict does NOT contain an `alt_text` key, regardless of whether the analysis has one.
8. **AC-08**: `TelegramPublisher` and `EmailPublisher` continue to function unchanged when context contains an `alt_text` key they don't use.

### Sidecar (Part C)

9. **AC-09**: When `extended_metadata_enabled=True` and `analysis.alt_text` is non-None, the sidecar metadata includes `"alt_text": "..."`.
10. **AC-10**: When `alt_text` is `None`, the sidecar metadata does NOT include an `alt_text` key (no "alt_text: null" in output).

### Web & Preview (Part D)

11. **AC-11**: `AnalysisResponse` includes `alt_text: str | None = None`. The `POST /api/images/{filename}/analyze` endpoint returns `alt_text` when available and `features.alt_text_enabled=True`.
12. **AC-12**: CLI preview mode displays `alt_text` in the vision analysis section when present.

### Backward Compatibility

13. **AC-13**: All existing tests pass without modification. Existing `ImageAnalysis` construction without `alt_text` keyword is unaffected (default `None`).

---

## Out of Scope

- **Retroactive alt text** for already-published images
- **Alt text for email** (images are MIME attachments, not web content)
- **Conditional vision prompt** — alt text is always requested from OpenAI (negligible cost); the feature flag gates downstream consumption only
- **Alt text editing in the web UI** — display only for now; editing can be a follow-up
- **Alt text validation/enforcement** (e.g., rejecting >125 chars from OpenAI) — we take what the model gives and truncate if needed
- **Instagram publisher integration** — Instagram is being removed (GH #67); Bluesky and Mastodon will consume alt text when implemented

## Preview Mode

No special handling needed. Vision analysis already runs in preview mode. Alt text will appear in preview output via `print_vision_analysis()`. No side effects.

## Implementation Notes

- **Token cost**: Negligible — `alt_text` adds ~30-40 completion tokens to an existing vision API call that already returns 15+ fields.
- **WCAG guidance**: 125 characters is the conventional maximum for effective alt text. The prompt instructs the model, but no hard truncation is applied on our side (model compliance is good enough).
- **Future publishers**: Bluesky (`app.bsky.embed.images` has `alt` field) and Mastodon (`POST /api/v2/media` has `description` field) will consume `context["alt_text"]` when implemented (PUB-027, PUB-030).

## Related

- [PUB-003: Expanded Vision Analysis](archive/PUB-003_expanded-vision-analysis.md) — the vision schema this extends
- [PUB-017: Multi-Platform Publishing](archive/PUB-017_multi-platform-publishing.md) — publisher interface
- [PUB-039: AI Caption Feature Flags](archive/PUB-039_ai-caption-feature-flags.md) — `alt_text_enabled` flag (already shipped)
- [GH #67](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/67) — Instagram publisher removal

---

2026-04-25 — Spec hardened for Claude Code handoff (Instagram ACs removed per product decision)
