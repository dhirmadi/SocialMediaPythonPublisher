# PUB-025: Platform-Adaptive Captions

| Field | Value |
|-------|-------|
| **ID** | PUB-025 |
| **Category** | AI |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Not Started |
| **Dependencies** | — |

## Problem

The publisher generates a single caption for all platforms, then applies superficial formatting (hashtag limits, length trim, FetLife sanitization) per platform via `format_caption()`. The caption content itself — tone, style, structure — is identical everywhere. This produces mediocre results: Telegram gets a caption optimized for Instagram's hashtag culture, and email gets a 2200-char caption trimmed down to 240 chars losing all nuance.

Currently `CaptionSpec.for_config()` picks one of two presets (`fetlife_email` or `generic`) based on whether email is enabled. There is no mechanism to generate distinct caption text per platform.

## Desired Outcome

Generate a tailored caption per enabled platform in a single AI call. Each caption matches the platform's native style, constraints, and audience expectations. Instead of one caption string formatted N ways, the workflow produces N caption strings — one per active platform — each purpose-built by the LLM.

## Scope

### Part A: `CaptionSpec` per platform (`core/models.py`)

Replace the single `CaptionSpec.for_config()` with a new factory that produces a dict of specs:

```python
@staticmethod
def for_platforms(config: ApplicationConfig) -> dict[str, CaptionSpec]:
    """Build a CaptionSpec per enabled publisher."""
```

Each spec contains the platform name, style directive, hashtag policy, and max length. The specs are derived from the **platform style registry** (Part C).

The existing `for_config()` method is preserved (deprecated, delegates to `for_platforms` returning the first/primary spec) for backwards compatibility with `web/service.py` and tests that use it.

### Part B: Multi-platform caption generation (`services/ai.py`)

New method on `CaptionGeneratorOpenAI`:

```python
async def generate_multi(
    self, analysis: ImageAnalysis, specs: dict[str, CaptionSpec]
) -> dict[str, str]:
    """Generate one caption per platform in a single OpenAI call.

    Returns: {"telegram": "...", "instagram": "...", "email": "..."}
    """
```

**Prompt design**: The user message enumerates each platform with its constraints:

```
Generate captions for these platforms:

1. telegram: conversational, emoji-friendly, up to 4096 chars. Include hashtags: #shibari #ropeart ...
2. instagram: hook-first, include hashtags naturally, up to 2200 chars. Include hashtags: #shibari #ropeart ...
3. email: engagement question style, no hashtags, up to 240 chars.

Image analysis: description='...', mood='...', tags=[...]

Respond with strict JSON: {"telegram": "...", "instagram": "...", "email": "..."}
```

- Uses `response_format={"type": "json_object"}` to ensure parseable JSON.
- Temperature: 0.7 (same as existing `generate`).
- Model: `self.model` (the `caption_model`).
- Each returned caption is length-enforced per its `spec.max_length` (truncate with ellipsis if needed).
- Missing platform keys in the LLM response → `AIServiceError`.
- System prompt: same `self.system_prompt` as existing `generate`.

**SD caption integration**: New method `generate_multi_with_sd` that extends the prompt to also produce `sd_caption` (same pattern as existing `generate_with_sd`, but with multi-platform captions):

```python
async def generate_multi_with_sd(
    self, analysis: ImageAnalysis, specs: dict[str, CaptionSpec]
) -> dict[str, str]:
    """Returns: {"telegram": "...", "instagram": "...", "email": "...", "sd_caption": "..."}"""
```

Uses `self.sd_caption_model`, `self.sd_caption_system_prompt`, `self.sd_caption_role_prompt` (same precedence rules as existing `generate_with_sd`).

**AIService changes**: New `create_multi_caption_pair_from_analysis`:

```python
async def create_multi_caption_pair_from_analysis(
    self, analysis: ImageAnalysis, specs: dict[str, CaptionSpec]
) -> tuple[dict[str, str], str | None]:
    """Returns (platform_captions_dict, sd_caption_or_none)."""
```

Follows same fallback pattern: try `generate_multi_with_sd` if SD enabled, fall back to `generate_multi` + `(captions, None)`.

### Part C: Platform style registry (`config/static/ai_prompts.yaml` + `static_loader.py`)

New `platform_captions` section in `ai_prompts.yaml`:

```yaml
platform_captions:
  telegram:
    style: "conversational, emoji-friendly, artistic commentary"
    max_length: 4096
    hashtags: true
  instagram:
    style: "hook-first, hashtags woven naturally, engaging, visual storytelling"
    max_length: 2200
    hashtags: true
  email:
    style: "engagement question, intimate, FetLife-appropriate, no hashtags"
    max_length: 240
    hashtags: false
  generic:
    style: "minimal_poetic"
    max_length: 2200
    hashtags: true
```

- Loaded via `get_static_config().ai_prompts.platform_captions`.
- Orchestrator-config override: if `config.openai` carries per-platform style overrides (future), those take precedence. For now, static YAML is the only source.
- `CaptionSpec.for_platforms()` reads this registry and filters to enabled publishers only.
- Unknown platforms fall back to `generic`.

### Part D: Workflow integration (`core/workflow.py`)

In `WorkflowOrchestrator.execute()`:

1. **Build specs**: `specs = CaptionSpec.for_platforms(self.config)` — one per enabled publisher.
2. **Generate**: `platform_captions, sd_caption = await self.ai_service.create_multi_caption_pair_from_analysis(analysis, specs)`.
3. **Publish**: Each publisher receives its own caption:
   ```python
   p.publish(tmp_path, format_caption(p.platform_name, platform_captions.get(p.platform_name, caption_fallback)), context=...)
   ```
4. **Fallback**: If `platform_captions` is empty (AI disabled, caption override, feature off), fall back to current behavior: one caption, format per platform.
5. **Caption override**: When `caption_override` is provided (web UI), it applies to all publishers (current behavior, no per-platform override).
6. **WorkflowResult**: `result.caption` becomes the primary platform's caption (for logging/sidecar). New `result.platform_captions: dict[str, str]` carries all per-platform captions.

### Part E: Preview mode (`app.py`)

Preview already loops publishers and calls `format_caption(pub.platform_name, result.caption)`. Change this to use `result.platform_captions.get(pub.platform_name, result.caption)` so preview shows the actual per-platform AI-generated captions.

### Part F: Web service (`web/service.py`)

`analyze_and_caption` currently returns a single `caption` in `AnalysisResponse`. For backwards compatibility:
- `AnalysisResponse.caption` remains the primary caption (first platform or generic).
- New optional field `AnalysisResponse.platform_captions: dict[str, str] | None` for web UI consumers that want per-platform preview.
- `WebImageService.analyze_and_caption` calls `for_platforms` + `create_multi_caption_pair_from_analysis`.

## Non-Goals

- No new publishers (PUB-027, PUB-030)
- No hashtag optimization logic (PUB-028)
- No brand voice matching (PUB-029)
- SD caption generation content/format is unchanged (still one `sd_caption`)
- No per-platform prompt configuration via orchestrator (future enhancement; YAML only for now)

## Acceptance Criteria

### Multi-platform generation

- **AC1**: When multiple publishers are enabled (e.g. telegram + instagram + email), `generate_multi` sends a single OpenAI API call and returns a `dict[str, str]` with a caption keyed by each platform name.
- **AC2**: Each returned platform caption respects its configured `max_length`. If the LLM exceeds the limit, the caption is truncated with ellipsis.
- **AC3**: If the LLM response is missing a requested platform key, `generate_multi` raises `AIServiceError`.
- **AC4**: `generate_multi` uses `response_format={"type": "json_object"}` to ensure parseable JSON.

### Platform styles

- **AC5**: Telegram captions use conversational style with emojis, up to 4096 chars, with hashtags.
- **AC6**: Instagram captions lead with a hook, include hashtags naturally, up to 2200 chars.
- **AC7**: Email/FetLife captions use engagement-question style, no hashtags, up to 240 chars.
- **AC8**: Platform style directives come from `ai_prompts.yaml` under `platform_captions.*`, not hardcoded in Python.

### Workflow integration

- **AC9**: Each publisher receives its platform-specific caption from `platform_captions[publisher.platform_name]`, not a generically formatted version of one caption.
- **AC10**: `format_caption()` still applies as a safety net after AI generation (length trim, hashtag cap, FetLife sanitization).
- **AC11**: When `caption_override` is provided (web UI publish), all publishers receive the override (current behavior preserved).
- **AC12**: When only one publisher is enabled, behavior is equivalent to today: a single-platform spec is sent to the LLM, one caption returned.

### SD caption

- **AC13**: `generate_multi_with_sd` produces per-platform captions plus one `sd_caption` in a single API call.
- **AC14**: SD caption content, format, and sidecar upload behavior are unchanged from PUB-001/PUB-004.
- **AC15**: When SD is disabled or `generate_multi_with_sd` fails, the system falls back to `generate_multi` and returns `(captions, None)` for SD.

### CaptionSpec

- **AC16**: `CaptionSpec.for_platforms(config)` returns a `dict[str, CaptionSpec]` with entries only for enabled publishers.
- **AC17**: Existing `CaptionSpec.for_config(config)` still works (deprecated but functional) — returns a single spec for the primary platform. Existing tests and `web/service.py` callers are not broken.

### Preview and web

- **AC18**: Preview mode displays all per-platform AI-generated captions (not format_caption variants of one caption).
- **AC19**: `AnalysisResponse` gains `platform_captions: dict[str, str] | None`. The `caption` field remains populated with the primary caption.

### Quality

- **AC20**: Zero new `ruff check` or `mypy` violations in touched files.
- **AC21**: Tests cover: multi-platform generation (mock OpenAI), single-platform fallback, SD integration, caption override, format_caption safety net, platform style loading, preview output, invalid LLM response handling.

## Implementation Notes

### Prompt construction

Build the platform enumeration dynamically from the specs dict:

```python
platform_lines = []
for i, (name, spec) in enumerate(specs.items(), 1):
    ht = f"Include hashtags: {spec.hashtags}." if spec.hashtags else "No hashtags."
    platform_lines.append(
        f"{i}. {name}: {spec.style}, up to {spec.max_length} chars. {ht}"
    )
platforms_block = "\n".join(platform_lines)
keys_list = ", ".join(f'"{k}"' for k in specs)
```

### Response parsing

```python
data = json.loads(content)
captions: dict[str, str] = {}
for platform in specs:
    val = data.get(platform)
    if val is None:
        raise AIServiceError(f"Missing platform '{platform}' in LLM response")
    caption_text = str(val).strip()
    if len(caption_text) > specs[platform].max_length:
        caption_text = caption_text[:specs[platform].max_length - 1].rstrip() + "…"
    captions[platform] = caption_text
```

### WorkflowResult changes

```python
@dataclass
class WorkflowResult:
    ...
    platform_captions: dict[str, str] = field(default_factory=dict)
```

`result.caption` = primary caption (first enabled platform or generic).
`result.platform_captions` = full dict when multi-platform generation was used.

### Static config extension

`AIPromptsConfig` gains a `platform_captions` field. If YAML section is missing, fall back to hardcoded defaults in `static_loader.py` (same pattern as existing prompt fallbacks).

### Cost neutrality

One API call with a slightly longer prompt (~200 extra tokens for 3 platforms) replaces one API call with a shorter prompt. Output tokens increase proportionally to platform count. Net cost delta is negligible.

## Related

- [PUB-001: Caption File](archive/PUB-001_caption-file.md) — original caption system
- [PUB-017: Multi-Platform Publishing](archive/PUB-017_multi-platform-publishing.md) — publisher interface this builds on
- [PUB-028: Smart Hashtag Generation](PUB-028_smart-hashtag-generation.md) — enhances hashtags within platform captions
- [PUB-029: Brand Voice Matching](PUB-029_brand-voice-matching.md) — adds voice consistency to per-platform captions

---

*2026-03-16 — Spec hardened for Claude Code handoff*
