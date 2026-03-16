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

The publisher generates a single caption for all platforms, then applies superficial formatting (hashtag limits, length trim, FetLife sanitization) per platform. The caption content itself — tone, style, structure — is identical everywhere. This produces mediocre results: Telegram gets a caption optimized for Instagram's hashtag culture, and Instagram gets a caption constrained by email's 240-char limit when email is enabled. In 2026, generic cross-posted captions are a clear signal of low-effort automation.

Currently `CaptionSpec.for_config()` picks one of two presets (`fetlife_email` or `generic`) based on whether email is enabled. There is no mechanism to generate distinct caption text per platform.

## Desired Outcome

Generate a tailored caption per enabled platform in a single AI call. Each caption matches the platform's native style, constraints, and audience expectations. From the publisher's perspective: instead of one caption string formatted N ways, the workflow produces N caption strings — one per active platform — each purpose-built.

## Scope

- Extend `CaptionSpec` to support per-platform specs (one per enabled publisher)
- New AI prompt that generates multiple platform-specific captions from the same vision analysis in a single call (JSON response with a key per platform)
- Update `CaptionGeneratorOpenAI` to accept multiple `CaptionSpec` entries and return a dict of `{platform: caption}`
- Update `WorkflowOrchestrator.execute()` to pass each publisher its own caption instead of formatting one caption N ways
- Retain `format_caption()` as a safety net (length trim, hashtag limit) but the AI should already respect platform constraints
- Per-platform style guidelines configurable via `ai_prompts.yaml` or orchestrator config

## Non-Goals

- No new publishers (that is PUB-027, PUB-028)
- No hashtag optimization logic (that is PUB-028)
- No brand voice matching (that is PUB-029)
- SD caption generation is unchanged

## Acceptance Criteria

- AC1: When multiple publishers are enabled, the AI generates a distinct caption per platform in a single API call
- AC2: Telegram captions use a conversational, emoji-friendly style up to 4096 chars
- AC3: Instagram captions lead with a hook, include hashtags, and stay within 2200 chars
- AC4: Email/FetLife captions use an engagement-question style within 240 chars with no hashtags
- AC5: Each publisher receives its platform-specific caption (not a generically formatted version of one caption)
- AC6: If only one publisher is enabled, behavior is equivalent to today (single caption, no regression)
- AC7: The per-platform prompt guidelines are configurable (YAML or orchestrator config), not hardcoded
- AC8: `format_caption()` still applies as a safety net after AI generation (length trim, hashtag cap)
- AC9: SD caption generation (`sd_caption`) is unaffected
- AC10: A single OpenAI API call generates all platform captions (no per-platform round-trips)
- AC11: Preview mode displays all per-platform captions

## Implementation Notes

- The AI prompt should enumerate which platforms need captions and their constraints; the response is JSON: `{"telegram": "...", "instagram": "...", "email": "..."}`
- `CaptionSpec` could become a list or dict keyed by platform name
- The `context` dict passed to `publish()` could carry the platform-specific caption, or the workflow could index into the dict by `publisher.platform_name`
- Future publishers (Bluesky, Threads) automatically get their own caption style by adding a spec entry
- Cost impact is neutral: one AI call with a slightly longer prompt replaces one AI call with a shorter prompt

## Related

- [PUB-001: Caption File](archive/PUB-001_caption-file.md) — original caption system
- [PUB-017: Multi-Platform Publishing](archive/PUB-017_multi-platform-publishing.md) — publisher interface this builds on
- [PUB-028: Smart Hashtag Generation](PUB-028_smart-hashtag-generation.md) — enhances hashtags within platform captions
- [PUB-029: Brand Voice Matching](PUB-029_brand-voice-matching.md) — adds voice consistency to per-platform captions
