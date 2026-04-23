# PUB-035: Caption Context Intelligence — History-Aware, Voice-Consistent AI Captions

| Field | Value |
|-------|-------|
| **ID** | PUB-035 |
| **Category** | AI |
| **Priority** | P1 |
| **Effort** | S–M |
| **Status** | Done |
| **Dependencies** | PUB-025 (Done) |

## Problem

The AI generates each caption in isolation. It has no memory of what was posted before, no examples of the desired voice, and no awareness of how people actually post content in 2026. This produces:

1. **Repetitive phrasing** — the same opening patterns, sentence structures, and word choices appear across posts because the LLM has no context to vary against.
2. **Generic AI tone** — without concrete examples of the creator's voice, the output sounds like "GPT wrote this" rather than matching the creator's authentic style.
3. **Dated style** — prompt instructions like "write an engaging caption" produce 2022-era social media copy. The AI doesn't know that 2026 Telegram art channels prefer short, direct commentary over flowery descriptions.

The data to solve all three problems **already exists** in the publisher: sidecars contain every past caption, and the style registry can hold examples and trend guidance. The AI just doesn't see any of it.

## Desired Outcome

Every caption generation call includes contextual intelligence drawn from three sources:

- **Style examples**: Curated human-written examples of the desired voice per platform (few-shot prompting)
- **Trend guidance**: Periodically updated instructions on current platform conventions and anti-patterns
- **Caption history**: The tenant's N most recent published captions, injected as context so the AI avoids repetition and maintains voice consistency

The result: captions that sound human, stay fresh, and evolve naturally over time — without a vector database, embeddings, or any additional infrastructure.

## Scope

### Part A — Style examples in the platform registry

Extend `ai_prompts.yaml` `platform_captions` entries with an `examples` list:

```yaml
platform_captions:
  telegram:
    style: "conversational, emoji-friendly, artistic commentary"
    max_length: 4096
    hashtags: true
    examples:
      - "The way light catches jute at golden hour — it's its own kind of alchemy ✨"
      - "New work. Three hours of tying, five minutes of perfection. That's the ratio nobody talks about."
      - "Sometimes silence says more than a caption ever could. But here we are."
```

The multi-platform prompt (from PUB-025's `generate_multi`) includes these examples in the user message:

```
Platform: telegram
Style: conversational, emoji-friendly, artistic commentary
Voice examples (match this tone, DO NOT copy):
  - "The way light catches jute at golden hour..."
  - "New work. Three hours of tying..."
```

If `examples` is empty or absent, the prompt omits the examples block (backwards-compatible).

### Part B — Trend guidance per platform

Add an optional `guidance` field to each platform entry:

```yaml
platform_captions:
  telegram:
    style: "conversational, emoji-friendly, artistic commentary"
    guidance: |
      2026 Telegram art channels: short captions (1-2 sentences), minimal emoji (1-2 max),
      direct artist commentary over poetic descriptions. Avoid "in a world where..." openings.
      Authenticity over polish. Audience values process insight and honest reactions.
    max_length: 4096
    hashtags: true
```

The prompt includes `guidance` as a platform-specific instruction block after the style directive.

### Part C — Caption history as sliding context window

At generation time, fetch the tenant's N most recent published captions from storage and inject them into the prompt.

**Data source**: Sidecar files (`.caption.json`) already exist in storage for every analyzed image. Each contains the published caption text.

**Fetch strategy**:
1. List objects in the tenant's image folder (use existing `storage.list_images()` or `storage.list_objects_v2()`)
2. For each of the N most recent files (by last_modified or name, configurable), check if a sidecar exists
3. Download and extract the `caption` field from each sidecar
4. Filter to the target platform's caption if platform-specific captions are available (PUB-025 stores per-platform captions in the sidecar)

**Window size**: Configurable via `ai_prompts.yaml`:

```yaml
caption_history:
  window_size: 8
  max_tokens_budget: 1000
```

If history retrieval fails (storage error, no sidecars yet), generation proceeds without history — it's an optional enhancement, never a blocker.

**Prompt injection** — after style examples, before the image analysis:

```
Your recent captions for this account (DO NOT repeat phrasing, vary structure and openings):
1. "The way light catches jute at golden hour..."
2. "New work. Three hours of tying, five minutes of perfection."
...

Now write a NEW caption that maintains voice consistency but uses DIFFERENT:
- Opening patterns
- Sentence structures
- Word choices
- Emotional angles
```

### Part D — Operator edit tracking (foundation)

When the operator edits a caption in the web UI before publishing, store both versions in the sidecar:

```json
{
  "caption": "The operator's edited version",
  "caption_generated": "The AI's original version",
  "caption_edited": true
}
```

The history context window (Part C) preferentially uses `caption` (the published/edited version) over `caption_generated`. This way the AI learns from what the operator actually published, not what it originally suggested.

Full reinforcement learning from edits (comparing generated vs published to improve prompts) is deferred to PUB-029 (Brand Voice Matching).

## Non-Goals

- Vector database / embeddings / RAG — not needed for a sliding window of N recent captions
- Fine-tuning or model training — we use prompt context, not weight updates
- Cross-tenant learning — each tenant's history is isolated
- Automated trend detection — trend guidance is manually curated in YAML
- Full brand voice profiling (that's PUB-029)
- Changes to existing sidecar schema (only additive field `caption_generated`)

## Acceptance Criteria

- AC1: `ai_prompts.yaml` `platform_captions` entries support an optional `examples` list (array of strings)
- AC2: When `examples` is non-empty, the multi-platform prompt includes a "Voice examples" block per platform
- AC3: `ai_prompts.yaml` `platform_captions` entries support an optional `guidance` string field
- AC4: When `guidance` is non-empty, the prompt includes it as a platform instruction block
- AC5: A configurable `caption_history.window_size` (default 8) controls how many recent captions are fetched
- AC6: At generation time, the N most recent sidecars are read from storage, captions extracted, and injected into the prompt as a "recent captions" context block
- AC7: If sidecar retrieval fails (storage error, no sidecars, empty folder), generation proceeds normally without history context
- AC8: The prompt includes explicit anti-repetition instructions when history is present
- AC9: When the operator edits a caption before publishing, the sidecar stores `caption_generated` (original AI output) alongside `caption` (published version)
- AC10: The history context window uses `caption` (published) not `caption_generated` (AI original)
- AC11: Token budget: history context does not exceed `caption_history.max_tokens_budget` (default 1000) — truncate oldest entries first
- AC12: `ruff` / `mypy` / `pytest` gates pass

## Implementation Notes

- **No new infrastructure**: no vector DB, no Redis, no external services. Uses existing storage + existing sidecar format + prompt engineering.
- **Token cost**: ~500-1000 extra input tokens per generation. With PUB-034 metering, this is automatically tracked.
- Parts A+B are YAML schema extensions + prompt construction changes in `ai.py`. Part C adds a sidecar-reading step before generation. Part D is a small change to the sidecar write path.
- The `StaticConfig` Pydantic model for `ai_prompts.yaml` needs extending: `examples: list[str] = []`, `guidance: str = ""`, and a new `CaptionHistoryConfig` model.
- Sidecar format: the existing `generate_and_upload_sidecar` in `services/sidecar.py` writes the sidecar — extend it to include `caption_generated` when the caption was edited.

## Related

- [PUB-025: Platform-Adaptive Captions](archive/PUB-025_platform-adaptive-captions.md) — multi-platform generation this extends
- [PUB-029: Brand Voice Matching](PUB-029_brand-voice-matching.md) — future: full voice profiling from edit patterns
- [PUB-028: Smart Hashtag Generation](PUB-028_smart-hashtag-generation.md) — history context could also inform hashtag variety
