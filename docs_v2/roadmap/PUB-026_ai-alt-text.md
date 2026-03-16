# PUB-026: AI Alt Text Generation

| Field | Value |
|-------|-------|
| **ID** | PUB-026 |
| **Category** | AI |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Not Started |
| **Dependencies** | — |

## Problem

Published images have no alt text. Instagram, Bluesky, and Threads all support alt text fields, and accessibility regulations increasingly require it. Our vision analysis already produces a rich structured description of every image (subject, lighting, composition, mood), but none of this is surfaced as alt text. We are sitting on the data and not using it.

## Desired Outcome

Every published image includes a concise, screen-reader-friendly alt text string generated from the existing vision analysis. Publishers that support alt text (Instagram, future Bluesky/Threads) pass it to the platform API. The alt text is also stored in the sidecar for traceability.

## Scope

- Add `alt_text` field to the vision analysis response (new key in the AI prompt)
- Store `alt_text` in `ImageAnalysis` dataclass
- Pass `alt_text` through the publish context to publishers
- Update `InstagramPublisher` to use `instagrapi`'s `accessibility_caption` parameter
- Include `alt_text` in the sidecar metadata (Phase 2 block)
- Display `alt_text` in the web UI image details view
- Feature flag: `features.alt_text_enabled` (default `true`)

## Non-Goals

- No retroactive alt text generation for already-published images
- No alt text for email (email images are attachments, not web content)
- No separate AI call — alt text is generated within the existing vision analysis call

## Acceptance Criteria

- AC1: Vision analysis JSON response includes an `alt_text` field: concise (≤125 chars), descriptive, no hashtags, no promotional language
- AC2: `ImageAnalysis` dataclass includes `alt_text: str | None`
- AC3: `InstagramPublisher.publish()` passes alt text via `accessibility_caption` (or equivalent instagrapi parameter)
- AC4: Alt text is included in the sidecar metadata when `captionfile.extended_metadata_enabled` is true
- AC5: Web UI image details endpoint returns `alt_text` in the response
- AC6: When `features.alt_text_enabled` is false, the `alt_text` field is omitted from the vision prompt and not generated
- AC7: Alt text is passed in the `context` dict to publishers; publishers that don't support it ignore it
- AC8: Preview mode displays alt text alongside other analysis fields
- AC9: Existing vision analysis fields are unaffected (no regression)

## Implementation Notes

- Add `alt_text` to the vision system prompt: "Generate a concise alt text (≤125 characters) describing the image for screen readers. Focus on what is visually depicted, not interpretation or mood."
- Instagram's `photo_upload` in instagrapi accepts an `extra_data` dict or `custom_accessibility_caption` field
- The 125-char limit follows WCAG best practices for alt text length
- Future publishers (Bluesky, Threads) will consume `alt_text` from context when they are added
- Cost impact: negligible — one additional short field in an existing API call

## Related

- [PUB-003: Expanded Vision Analysis](archive/PUB-003_expanded-vision-analysis.md) — the vision schema this extends
- [PUB-017: Multi-Platform Publishing](archive/PUB-017_multi-platform-publishing.md) — publisher interface
