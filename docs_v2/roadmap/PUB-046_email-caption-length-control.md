# PUB-046 — Email Caption Length Control

| Field | Value |
|-------|-------|
| **ID** | PUB-046 |
| **Category** | AI |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Not Started |
| **Dependencies** | PUB-025 (Done), PUB-029 (Done), PUB-039 (Done) |
| **GitHub Issue** | #73 |

---

## Problem

Captions generated for the FetLife email platform routinely exceed the configured 240-character limit. The LLM ignores character-count instructions — a well-documented limitation — generating 260–350 characters. The code correctly truncates via `smart_truncate` → `format_caption` → `_sanitize_for_fetlife` → `_trim_to_length`, but truncation produces awkward mid-thought cut-offs that often remove the engagement question (the most important part of the caption for FetLife).

Root causes:

1. **LLMs cannot count characters.** Research confirms word-count constraints ("at most X words") dramatically outperform character-count constraints across all major model families.
2. **Prompt asks for too much content.** The current role prompt demands 1–2 sentences + sensual detail + an open question — effectively 3 content clauses that naturally produce 250–350 characters.
3. **No few-shot examples for email.** The `PlatformCaptionStyle` model supports `examples` and `guidance` fields, and `build_platform_block` renders them — but the email section in `ai_prompts.yaml` uses neither. Few-shot examples are the single most effective technique for controlling output length.
4. **No `max_tokens` on caption API calls.** Vision analysis sets `max_tokens` but caption generation does not, allowing unbounded token generation.
5. **Truncation destroys meaning.** `smart_truncate` cuts at sentence/word boundaries, which typically removes the trailing question — the engagement hook.

## Solution

A layered fix combining prompt engineering best practices with mechanical safety nets:

### Part A — Few-Shot Examples & Guidance in `ai_prompts.yaml`

Add curated `examples` (3–5 captions at the target length) and `guidance` to the email platform config. The infrastructure already exists — `PlatformCaptionStyle.examples`, `PlatformCaptionStyle.guidance`, and `build_platform_block` all support this. This is the highest-impact change: showing the model examples at exactly the right length calibrates output length better than any instruction.

**Config change in `config/static/ai_prompts.yaml`:**

```yaml
email:
    style: "one intimate sentence + one brief question, FetLife-appropriate, no hashtags"
    max_length: 240
    hashtags: false
    examples:
      - "Soft rope, steady hands, and a gaze that doesn't flinch. What does trust look like on you?"
      - "This kind of tension doesn't need words. But tell me — what caught your eye first?"
      - "Bare skin, bold lines, quiet surrender. What would you add to this scene?"
      - "Silk and steel have more in common than you think. Which one draws you in?"
    guidance: "FetLife email subject. Aim for 30-35 words. One flirtatious observation + one open question. Never exceed 40 words."
```

### Part B — Word-Count Length Instructions

Switch the primary length constraint from characters to words throughout the prompt pipeline. 240 characters ≈ 40 words (at ~6 chars/word). Word-based constraints achieve dramatically better compliance because LLMs tokenize in word-like chunks.

**Changes:**

1. `build_platform_block` in `services/ai.py`: for `max_length <= 300`, emit word-based instruction:
   - Before: `"STRICT LIMIT: 240 characters maximum (this is a hard limit, will be truncated if exceeded)"`
   - After: `"STRICT LIMIT: 40 words maximum (aim for 30-35 words). Will be truncated if exceeded."`
2. Same change in the single-platform `generate` method's `length_instruction`.
3. Keep the character-count mechanical truncation as-is (the safety net).

### Part C — `max_tokens` Ceiling for Short-Limit Platforms

Add `max_tokens` to all caption API calls when any spec has `max_length <= 300`. This prevents extreme overshoots (350+ chars) while leaving enough headroom for normal generation.

**Threshold constant**: `SHORT_LIMIT_THRESHOLD = 300` — defined once in `services/ai.py` and used for all short-limit decisions (max_tokens, temperature, word-count instructions).

**Token budgets:**

| Call type | Condition | `max_tokens` value |
|-----------|-----------|-------------------|
| Single-platform (`generate`) | `spec.max_length <= 300` | `80` (~320 chars) |
| Single-platform + SD (`generate_with_sd`) | `spec.max_length <= 300` | `256` (JSON with caption + sd_caption) |
| Multi-platform (`generate_multi`) | Any spec has `max_length <= 300` | `512` (JSON with all platform captions) |
| Multi-platform + SD (`generate_multi_with_sd`) | Any spec has `max_length <= 300` | `512` (JSON with all platform captions + sd_caption) |

Rationale: single-platform calls produce one string (~60 tokens for 240 chars); multi-platform calls produce a JSON object with 3+ keys (telegram ~200 tokens + instagram ~100 tokens + email ~60 tokens + JSON overhead). The 512 budget is generous to avoid clipping long-form platform captions in the same response.

**Affected methods in `services/ai.py`:**
- `CaptionGeneratorOpenAI.generate`
- `CaptionGeneratorOpenAI.generate_with_sd`
- `CaptionGeneratorOpenAI.generate_multi`
- `CaptionGeneratorOpenAI.generate_multi_with_sd`

### Part D — Two-Pass Condense on Overshoot

Replace dumb truncation with an AI condense pass for short-limit platforms. When a generated caption exceeds `max_length` for a platform with `max_length <= SHORT_LIMIT_THRESHOLD`:

1. Make a second API call to shorten the caption while preserving tone and structure.
2. If the condense result fits within `max_length`, use it. Otherwise fall back to `smart_truncate`.
3. Log `caption_condensed` event for telemetry (or `caption_condense_failed` on fallback).

**Condense call specification:**

| Parameter | Value |
|-----------|-------|
| Model | Same as `self.model` (caption_model) |
| System prompt | `"You are a text editor. Shorten the given text to fit the character limit. Preserve the tone, meaning, and any questions. Return ONLY the shortened text."` |
| User prompt | `"Shorten this to under {max_length} characters. Keep the same tone and preserve any question at the end:\n\n{caption}"` |
| Temperature | `0.3` (low variance — we want predictable shortening) |
| `max_tokens` | `80` |
| Rate limiting | Goes through the existing `_rate_limiter` |

**Error handling:** If the condense API call fails for any reason (network error, rate limit, OpenAI error), log `caption_condense_failed` and fall back silently to `smart_truncate`. Never raise from the condense path.

**Where it runs:** The condense pass is applied inside `_parse_platform_captions` for multi-platform calls (where per-platform truncation already happens) and inside `generate` / `generate_with_sd` for single-platform calls. A new private method `_condense_caption(caption, max_length)` encapsulates the logic.

Cost: ~$0.0001 per condense call. Latency: ~200–400ms. Only fires on overshoot, which after Parts A–C should be <20% of captions.

### Part E — Temperature Reduction for Short-Limit Platforms

Lower `temperature` from `0.7` to `0.5` for caption calls when any spec has `max_length <= SHORT_LIMIT_THRESHOLD`. Lower temperature tightens the output distribution, improving length compliance without meaningfully reducing creativity (vision analysis already uses `0.4`).

**Behavior by method:**

| Method | Condition | Temperature |
|--------|-----------|-------------|
| `generate` | `spec.max_length <= 300` | `0.5` |
| `generate` | `spec.max_length > 300` | `0.7` (unchanged) |
| `generate_with_sd` | `spec.max_length <= 300` | `0.5` |
| `generate_with_sd` | `spec.max_length > 300` | `0.6` (unchanged) |
| `generate_multi` | Any spec has `max_length <= 300` | `0.5` |
| `generate_multi` | No spec has `max_length <= 300` | `0.7` (unchanged) |
| `generate_multi_with_sd` | Any spec has `max_length <= 300` | `0.5` |
| `generate_multi_with_sd` | No spec has `max_length <= 300` | `0.6` (unchanged) |

### Part F — Tenant Prompt Recommendations (Documentation)

Document recommended tenant prompt patterns for short-format platforms. This is a documentation deliverable, not a code change — the tenant prompts live in the orchestrator and are updated per-tenant.

**Recommended system prompt pattern:**
> You write ultra-short captions for FetLife email subjects. Kinky, playful, respectful, consent-forward. No hashtags, no emojis. ONE observation + ONE question — nothing more. Aim for 30-35 words. Hard ceiling: 40 words.

**Recommended role prompt pattern:**
> WORD LIMIT: 35 words max. Write one flirtatious observation about the image, then one brief question. Kinky, playful, FetLife-native. No hashtags, no emojis.

Key principles:
- Length constraint **first**, not buried at the end.
- Word count, not character count.
- Explicit content structure: "ONE + ONE — nothing more" (prevents 3-clause overshoot).

---

## Non-Goals

- Changing the FetLife character limit without empirical verification (the 240 vs 264 question is tracked separately in issue #73).
- Changing caption generation for platforms with `max_length > 300` (telegram, instagram) — they have no truncation problem.
- Fine-tuning or training a custom model for short captions.

## Acceptance Criteria

### Prompt & config (Part A, B)

- [ ] **AC-01**: Email platform config in `ai_prompts.yaml` includes ≥3 few-shot `examples` (each ≤240 chars) and a non-empty `guidance` string containing a word-count instruction.
- [ ] **AC-02**: `build_platform_block` emits a word-count instruction (containing "words") for specs with `max_length <= 300`, and a character-count instruction for specs with `max_length > 300`.
- [ ] **AC-03**: The email style text in `ai_prompts.yaml` drives "one sentence + one question" structure (not the old multi-clause "engagement question, intimate" formulation).

### API constraints (Part C, E)

- [ ] **AC-04**: When `spec.max_length <= 300`, single-platform `generate` passes `max_tokens=80` to the OpenAI API call. When `spec.max_length > 300`, no `max_tokens` is set.
- [ ] **AC-05**: When any spec has `max_length <= 300`, multi-platform `generate_multi` and `generate_multi_with_sd` pass `max_tokens=512`.
- [ ] **AC-06**: When any spec has `max_length <= 300`, caption API calls use `temperature=0.5`. When no spec is short-limit, existing temperatures are preserved (`0.7` for generate/generate_multi, `0.6` for SD variants).

### Condense pass (Part D)

- [ ] **AC-07**: When a generated caption exceeds `max_length` for a platform with `max_length <= 300`, `_condense_caption` is called before `smart_truncate`. If the condense result fits within `max_length`, it is returned. If condense itself exceeds the limit, `smart_truncate` is applied to the original.
- [ ] **AC-08**: If the condense API call fails (any exception), the code falls back silently to `smart_truncate` without raising.
- [ ] **AC-09**: A `caption_condensed` structured log event is emitted on successful condense, with fields: `original_length`, `condensed_length`, `max_length`, `platform`. A `caption_condense_failed` event is emitted when condense fails or its result still exceeds the limit.

### Regression safety

- [ ] **AC-10**: Telegram and Instagram caption generation uses the same `temperature` and `max_tokens` settings as before when no short-limit spec is present. Word-count instructions are not emitted for `max_length > 300`.
- [ ] **AC-11**: All existing caption tests pass (with expected updates to `test_email_style_in_prompt` which asserts the old email style text).

### Documentation (Part F)

- [ ] **AC-12**: Recommended tenant prompt patterns for short-format platforms are documented in this spec (Part F section).

## Implementation Notes

### Files affected

| File | Changes |
|------|---------|
| `publisher_v2/src/publisher_v2/config/static/ai_prompts.yaml` | Add `examples`, `guidance` to email; update email `style` |
| `publisher_v2/src/publisher_v2/config/static/platform_limits.yaml` | No change |
| `publisher_v2/src/publisher_v2/services/ai.py` | Add `SHORT_LIMIT_THRESHOLD` constant; update `build_platform_block` for word-count; add `max_tokens` + `temperature` logic to all 4 caption methods; add `_condense_caption` method; update `_parse_platform_captions` to call condense before truncation |
| `publisher_v2/src/publisher_v2/utils/captions.py` | No change (truncation remains as safety net) |
| `publisher_v2/tests/test_ai_email_length_control.py` | **New** — all PUB-046 tests |
| `publisher_v2/tests/test_ai_multi_caption.py` | Update `test_email_style_in_prompt` to assert new email style text |

### Condense method signature

```python
async def _condense_caption(self, caption: str, max_length: int, platform: str) -> str:
    """Attempt to shorten caption via a second API call. Returns original on failure."""
```

This method lives on `CaptionGeneratorOpenAI`. It is `async` because it makes an OpenAI API call. It catches all exceptions internally and returns the original caption on failure (never raises).

### `_parse_platform_captions` change

Currently `_parse_platform_captions` is a `@staticmethod`. To call `_condense_caption` (which needs `self.client`), it must either:
- Become a regular method (preferred — minimal change), or
- Accept the condense callable as a parameter.

The recommended approach is to make it a regular method.

### Known test update

`test_ai_multi_caption.py::TestPlatformStylesInPrompt::test_email_style_in_prompt` asserts `"engagement question" in user_msg.lower()`. After the style change in `ai_prompts.yaml`, this assertion must be updated to match the new style text. This is an expected change, not a regression.

### Risk mitigation

- The condense pass is behind the existing overshoot check (`len(content) > spec.max_length`), so it only fires when needed.
- `smart_truncate` remains as the final safety net if the condense pass also overshoots or fails.
- Multi-platform calls use a generous `max_tokens=512` to avoid clipping long-form platform captions in the same response.
- Temperature and max_tokens changes only apply when `max_length <= SHORT_LIMIT_THRESHOLD` — long-form platforms are unaffected.

### Testing strategy

1. **Prompt format tests** (AC-02, AC-03): assert `build_platform_block` emits word-count instructions for short-limit specs and character-count for long-limit specs. Assert email examples and guidance render in the prompt.
2. **API constraint tests** (AC-04, AC-05, AC-06): use `_FakeCompletions` mock pattern (from `test_ai_multi_caption.py`) to capture OpenAI `create()` kwargs; assert `max_tokens` and `temperature` values per scenario.
3. **Condense pass tests** (AC-07, AC-08, AC-09): mock the condense API call separately; test happy path (condense fits), condense-still-too-long path (falls back to smart_truncate), and condense-failure path (exception → fallback). Assert log events via `caplog`.
4. **Regression tests** (AC-10, AC-11): verify telegram-only and instagram-only specs produce calls with no `max_tokens` and original temperatures.

## Related

- GitHub Issue: #73 (FetLife email captions frequently exceed length limit)
- `publisher_v2/src/publisher_v2/config/static/platform_limits.yaml`
- `publisher_v2/src/publisher_v2/config/static/ai_prompts.yaml`
- `publisher_v2/src/publisher_v2/services/ai.py` — prompt construction, `smart_truncate`, caption generation
- `publisher_v2/src/publisher_v2/utils/captions.py` — `format_caption`, `_sanitize_for_fetlife`, `_trim_to_length`
- PUB-025 (Platform-Adaptive Captions) — introduced per-platform caption specs
- PUB-029 (Brand Voice Matching) — introduced voice examples infrastructure
- PUB-039 (AI Caption Feature Flags) — tenant-configurable AI settings

---

*2025-05-13 — Spec hardened for Claude Code handoff*
