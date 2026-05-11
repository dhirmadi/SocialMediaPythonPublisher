# PUB-028: Smart Hashtag Generation

| Field | Value |
|-------|-------|
| **ID** | PUB-028 |
| **Category** | AI |
| **Priority** | P2 |
| **Effort** | S |
| **Status** | Not Started |
| **Dependencies** | PUB-025 (Done — Platform-Adaptive Captions), PUB-041 (Done — `build_analysis_context`) |

## Problem

Hashtags are currently a static string from config (`content.hashtag_string`) appended verbatim to every caption identically. This produces generic hashtags that don't reflect the specific image content. Meanwhile, the vision analysis already extracts rich content signals (tags, mood, aesthetic_terms, style) that could drive intelligent hashtag selection — but none of this feeds into hashtag generation.

Additionally, platform hashtag conventions vary: Telegram and Email don't benefit from hashtags at all, but `ai_prompts.yaml` currently sets `telegram.hashtags: true`, causing unnecessary hashtag injection.

## Solution

When `features.smart_hashtags_enabled` is `True`, change the caption prompt's hashtag clause from "append these verbatim" to "generate relevant hashtags from the image analysis, optionally including these seed tags". This requires **no additional OpenAI API call** — hashtag intelligence is embedded in the existing per-platform caption prompt (PUB-025's `build_platform_block` / `_build_multi_prompt`).

When the flag is `False`, behavior falls back to the current static `hashtag_string` verbatim append.

---

## Parts

### Part A — Wire `smart_hashtags_enabled` into Caption Prompts

**Modify `build_platform_block()`** (`services/ai.py`):

Today's hashtag clause (when `spec.hashtags` is non-empty):
```
"Include hashtags: {spec.hashtags}."
```

When `smart_hashtags_enabled=True`, replace with:
```
"Generate 3-8 relevant hashtags based on the image analysis (tags, mood, style, aesthetic_terms).
 Format: lowercase, #-prefixed, no spaces. Weave them naturally at the end of the caption.
 {seed_clause}"
```

Where `seed_clause` is `"Always include these seed hashtags: {spec.hashtags}."` if `spec.hashtags` is non-empty, or empty if no seeds.

When `smart_hashtags_enabled=False`: keep the existing verbatim clause unchanged.

The `smart_hashtags_enabled` flag needs to flow into `build_platform_block()`. Options:
1. Add it as a parameter to `build_platform_block()`
2. Add a `smart_hashtags: bool` field to `CaptionSpec`

**Option 2 is cleaner** — `CaptionSpec` already carries per-platform config. Add `smart_hashtags: bool = False` to `CaptionSpec`, set it in `for_platforms()` from `config.features.smart_hashtags_enabled`.

### Part B — Fix Platform Hashtag Config

**Update `ai_prompts.yaml`**:

| Platform | Current `hashtags` | New `hashtags` | Rationale |
|----------|-------------------|----------------|-----------|
| `telegram` | `true` | `false` | Telegram channels don't use hashtags; they clutter the message |
| `email` | `false` | `false` (no change) | FetLife email doesn't support hashtags |
| `generic` | `true` | `true` (no change) | Fallback for unknown platforms |

This ensures `CaptionSpec.hashtags` is `""` for Telegram, so the prompt says "No hashtags." regardless of the `smart_hashtags_enabled` flag.

### Part C — `generate()` and `generate_with_sd()` Alignment

The single-platform paths (`generate()`, `generate_with_sd()`) also have hashtag clauses. These must be updated with the same smart vs verbatim branching:

- When `spec.smart_hashtags=True` and `spec.hashtags` is non-empty: "Generate relevant hashtags from the analysis. Include these seeds: {spec.hashtags}."
- When `spec.smart_hashtags=True` and `spec.hashtags` is empty: "Generate 3-8 relevant hashtags from the analysis."
- When `spec.smart_hashtags=False`: existing verbatim clause

### Part D — Hashtag Formatting Post-Generation

AI-generated hashtags may not always be perfectly formatted. Add a lightweight cleanup pass:

**New helper `normalize_generated_hashtags(text: str, max_count: int = 30) -> str`** in `utils/captions.py`:

1. Extract all `#\w+` tokens from the text
2. Lowercase, deduplicate (preserving order)
3. Cap at `max_count`
4. Rebuild the text with cleaned hashtags

This is applied in `format_caption()` when `smart_hashtags_enabled=True`, reusing the existing platform-specific formatting pipeline.

### Part E — Preview Display

Update `print_vision_analysis()` or `print_caption()` in `utils/preview.py` to show generated hashtags per platform alongside the caption. The existing `hashtag_count = caption.count("#")` pattern already works for AI-generated hashtags.

---

## Acceptance Criteria

### Prompt Intelligence (Part A)

1. **AC-01**: `CaptionSpec` has a new field `smart_hashtags: bool = False`. `CaptionSpec.for_platforms()` sets it to `True` when `config.features.smart_hashtags_enabled` is `True`.
2. **AC-02**: When `spec.smart_hashtags=True` and `spec.hashtags` (seed string) is non-empty, `build_platform_block()` produces a prompt clause instructing the AI to generate relevant hashtags and include the seeds.
3. **AC-03**: When `spec.smart_hashtags=True` and `spec.hashtags` is empty, the prompt clause instructs the AI to generate relevant hashtags without seeds.
4. **AC-04**: When `spec.smart_hashtags=False`, the prompt clause uses the existing verbatim hashtag append (`"End with these hashtags verbatim: ..."`).
5. **AC-05**: `generate()` and `generate_with_sd()` use the same smart vs verbatim branching as `build_platform_block()`.

### Platform Config (Part B)

6. **AC-06**: `ai_prompts.yaml` sets `telegram.hashtags: false`. Telegram captions never contain hashtag instructions in the prompt.
7. **AC-07**: `email.hashtags` remains `false`. Email captions are unaffected.

### Fallback (Part A)

8. **AC-08**: When `features.smart_hashtags_enabled=False`, all caption generation paths use the verbatim `hashtag_string` behavior — identical to pre-PUB-028 behavior.

### Formatting (Part D)

9. **AC-09**: AI-generated hashtags in the final caption are lowercase and `#`-prefixed. Duplicates are removed.

### No Extra API Call

10. **AC-10**: Smart hashtag generation does not add any additional OpenAI API calls. Hashtags are generated as part of the existing caption prompt.

### Preview (Part E)

11. **AC-11**: CLI preview mode displays hashtag count per platform in the caption output (existing `caption.count("#")` pattern works).

### Backward Compatibility

12. **AC-12**: When `smart_hashtags_enabled=False` and `content.hashtag_string` is set, the exact pre-PUB-028 behavior is preserved (verbatim hashtag append, same prompt text).
13. **AC-13**: Existing tests pass without modification (no regression in caption generation for current behavior).

---

## Out of Scope

- **Bluesky-specific hashtag handling** (AT Protocol facets) — deferred to PUB-027. When Bluesky is implemented, it will consume the smart hashtags from the caption text or `CaptionSpec`.
- **Hashtag performance tracking / analytics**
- **Hashtag A/B testing**
- **Trending hashtag lookups via external APIs**
- **Changes to the vision analysis prompt** — uses existing `ImageAnalysis` fields
- **Instagram hashtag handling** — Instagram is being removed (GH #67)

## Preview Mode

No special handling needed. Smart hashtags are part of caption generation, which already runs in preview mode. The preview output displays hashtag counts via existing patterns.

## Implementation Notes

- **No new dependencies** — `smart_hashtags_enabled` and `hashtag_string` are already wired in config
- **`build_analysis_context()`** (PUB-041) already provides `tags`, `mood`, `aesthetic_terms`, `style` in the caption prompt — the AI has all the signals it needs to generate relevant hashtags
- **`normalize_tags()`** in `utils/captions.py` already handles lowercase + dedup + `#` stripping for tag lists — can be adapted for hashtag post-processing
- **Token cost**: Negligible — hashtag instructions add ~20-30 prompt tokens; generated hashtags add ~20-40 completion tokens within the existing caption call
- **The `subject` field** is excluded from `build_analysis_context()` — this is fine; `tags` and `mood` carry sufficient signal for hashtag generation

## Related

- [PUB-025: Platform-Adaptive Captions](archive/PUB-025_platform-adaptive-captions.md) — the per-platform caption system hashtags integrate into
- [PUB-041: Vision Cost Optimization](archive/PUB-041_vision-cost-optimization.md) — `build_analysis_context()` provides vision data to prompts
- [PUB-027: Bluesky Publisher](PUB-027_bluesky-publisher.md) — future consumer of smart hashtags
- [GH #67](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/67) — Instagram removal

---

2026-05-08 — Spec hardened for Claude Code handoff
