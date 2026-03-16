# PUB-000: Preview Mode

| Field | Value |
|-------|-------|
| **ID** | PUB-000 |
| **Category** | Foundation |
| **Priority** | INF |
| **Effort** | S |
| **Status** | Done |
| **Dependencies** | — |

## Problem

Operators need to test configuration and see exactly what will be published without taking any actions. Without a side-effect-free preview, tuning AI prompts, verifying platform selection, and checking caption quality would require risky trial runs or manual inspection of internal state.

## Desired Outcome

A `--preview` mode that runs the full AI pipeline (vision analysis, caption generation) and displays human-readable output showing configuration, image details, vision analysis, generated captions, and platform preview — while guaranteeing no publishing, no archiving, and no state/cache updates.

## Scope

- Configuration summary (config path, vision/caption models)
- Image details (filename, folder, SHA256, Dropbox URL, posted status)
- AI vision analysis (description, mood, tags, NSFW, safety labels)
- Generated caption (platform, style, length, text, hashtags)
- Platform preview (enabled/disabled per platform, caption per platform, resizing info)
- Guarantees: zero API calls to platforms, no Dropbox moves, no cache updates
- `--select` support for previewing a specific image

## Acceptance Criteria

- AC1: Preview mode runs full AI pipeline without publishing to any platform
- AC2: No images moved or archived on Dropbox
- AC3: No state/cache updates
- AC4: Human-readable output shows configuration, vision analysis, caption, and platform preview
- AC5: Same image can be previewed multiple times (repeatable)
- AC6: `--select <filename>` previews a specific image

## Implementation Notes

- CLI flag: `--preview`
- Output format: human-readable (distinct from `--debug` JSON logs)
- Preview utilities in `utils/preview`; integrates with `WorkflowOrchestrator`
- Makefile target: `make preview-v2 CONFIG=...`

## Related

- [Original feature doc](../../08_Epics/000_v2_foundation/000_preview_mode/000_feature.md) — full historical detail
