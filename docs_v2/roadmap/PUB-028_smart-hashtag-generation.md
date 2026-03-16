# PUB-028: Smart Hashtag Generation

| Field | Value |
|-------|-------|
| **ID** | PUB-028 |
| **Category** | AI |
| **Priority** | P2 |
| **Effort** | S |
| **Status** | Not Started |
| **Dependencies** | PUB-025 |

## Problem

Hashtags are currently a static string from config (`content.hashtag_string`) appended to every caption identically. This produces a generic hashtag wall that hurts discoverability — Instagram's 2026 algorithm penalizes repetitive tag sets, and best practice is a 30% popular / 70% niche mix tailored to the specific image content. Meanwhile, platforms like Telegram and Email don't use hashtags at all, but our system treats them as a universal concern.

The vision analysis already extracts rich content signals (tags, mood, subject, style, aesthetic_terms) that could drive intelligent hashtag selection, but none of this feeds into hashtag generation.

## Desired Outcome

AI-generated, image-specific hashtags per platform, informed by the vision analysis. Instagram gets a curated mix of popular reach tags and niche discovery tags. Bluesky gets a small set of AT Protocol tags. Telegram and Email get no hashtags. The static `hashtag_string` config becomes an optional seed/override, not the sole source.

## Scope

- New hashtag generation step in the caption pipeline: vision analysis → hashtag generation → caption generation
- AI prompt that takes vision analysis fields (tags, mood, subject, style, aesthetic_terms) and produces a ranked hashtag set per platform
- Platform-specific hashtag strategy: Instagram (up to 30, popular/niche mix), Bluesky (up to 5, topical), Telegram (none), Email (none)
- Optional seed hashtags from config (`content.hashtag_string`) merged with AI-generated tags
- Hashtag deduplication and formatting (lowercase, no spaces, `#` prefix)
- Feature flag: `features.smart_hashtags_enabled` (default `true`); when disabled, falls back to static `hashtag_string`

## Non-Goals

- No hashtag performance tracking or analytics (that would require post-publish data ingestion)
- No hashtag A/B testing
- No trending hashtag lookups via external APIs
- No changes to the vision analysis prompt itself

## Acceptance Criteria

- AC1: When `features.smart_hashtags_enabled` is true, hashtags are AI-generated per platform from vision analysis data
- AC2: Instagram receives up to 30 hashtags with a mix of reach tags (broader) and niche tags (specific to image content)
- AC3: Bluesky receives up to 5 topical hashtags suitable for AT Protocol facets
- AC4: Telegram and Email captions contain no hashtags
- AC5: Static `content.hashtag_string` values are included as seed tags (always present) alongside AI-generated tags
- AC6: When `features.smart_hashtags_enabled` is false, behavior falls back to current static hashtag append
- AC7: Generated hashtags are lowercase, deduplicated, and properly `#`-prefixed
- AC8: Hashtag generation does not require an additional OpenAI API call when used with platform-adaptive captions (PUB-025) — hashtags are part of the per-platform caption prompt
- AC9: Preview mode displays generated hashtags per platform
- AC10: The hashtag generation prompt/strategy is configurable via `ai_prompts.yaml`

## Implementation Notes

- Cleanest approach: integrate hashtag generation into the per-platform caption prompt from PUB-025 — the AI already knows the platform constraints, so it can embed appropriate hashtags directly in each caption
- Alternative: separate hashtag generation call that returns `{"instagram": ["#tag1", ...], "bluesky": ["#tag1", ...]}` and feeds into caption formatting
- The vision analysis `tags` field (10-25 items, ordered by relevance) is a strong signal for niche hashtags
- `aesthetic_terms` and `style` fields inform photography/art community hashtags
- Instagram hashtag best practice (2026): 3-5 broad reach tags + 15-20 niche content tags + 5-10 community tags
- Dependency on PUB-025: if platform-adaptive captions are not yet implemented, hashtag generation can still work by injecting tags into the single caption per platform via `format_caption()`

## Related

- [PUB-025: Platform-Adaptive Captions](PUB-025_platform-adaptive-captions.md) — the per-platform caption system hashtags integrate into
- [PUB-003: Expanded Vision Analysis](archive/PUB-003_expanded-vision-analysis.md) — vision data that drives hashtag selection
- [PUB-027: Bluesky Publisher](PUB-027_bluesky-publisher.md) — consumes Bluesky-specific hashtags as facets
