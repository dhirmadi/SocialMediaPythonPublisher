# PUB-004: Caption File Extended Metadata

| Field | Value |
|-------|-------|
| **ID** | PUB-004 |
| **Category** | AI |
| **Priority** | INF |
| **Effort** | S |
| **Status** | Done |
| **Dependencies** | PUB-001 |

## Problem

Caption files contain only a single training caption, losing valuable context about image identity, analysis provenance, artistic attributes, and moderation signals. This limits dataset searchability, deduplication accuracy, traceability of model versions, and the ability to segment or refine data over time without external databases.

## Desired Outcome

Add a structured, comment-prefixed metadata block beneath the first-line Stable Diffusion caption. The first line remains the pure caption for training compatibility. The appended block captures identity, versioning, analysis context, and artistic descriptors for richer dataset curation, querying, and automation. Preserves existing workflows while enabling downstream analytics and iterative re-captioning.

## Scope

- First line: pure `sd_caption` only (unchanged)
- Separator: `# ---` on line 2
- Phase 1 metadata (default): image_file, dropbox_file_id, dropbox_rev, sha1, created (UTC ISO8601), sd_caption_version, model_version
- Phase 2 metadata (config flag): lighting, pose, materials, art_style, tags (JSON array), moderation (JSON array); plus subject, camera, composition, background, color_palette, aesthetic_terms when available
- All metadata lines prefixed with `# `
- Atomic overwrite; archived side-by-side with image on move
- Preview/dry-run: no file writes; preview prints full caption and metadata block

## Acceptance Criteria

- AC1: Given a generated `sd_caption`, when writing `<image>.txt`, then the first line is exactly the `sd_caption` with no trailing inline metadata
- AC2: Given caption file generation, when metadata is appended, then all metadata lines are prefixed with `# ` and an initial `# ---` separator appears on the next line after the caption
- AC3: Given metadata output Phase 1, when files are written, then the block includes: image_file, dropbox_file_id (if available), dropbox_rev (if available), sha1, created (UTC ISO8601), sd_caption_version, model_version
- AC4: Given metadata output Phase 2 (flagged), when enabled, then the block additionally includes contextual fields and analysis details
- AC5: Given preview or dry-run mode, when generating outputs, then no files are created or mutated; preview prints show the full caption and metadata block
- AC6: Given reprocessing of the same image, when writing `<image>.txt`, then the file is overwritten atomically and archived side-by-side with the image on move
- AC7: Given training pipelines that read only the first line, when this change is deployed, then training outcomes remain unaffected
- AC8: Given metadata fields are unavailable, when writing the block, then missing fields are omitted rather than populated with null-like placeholders

## Implementation Notes

- Phase 1 on by default; Phase 2 behind `captionfile.extended_metadata=true`
- Optional `--no-caption-metadata` CLI flag to hard-disable
- Prefer SHA256 to match repo dedup standard
- Implement in existing caption file writer path; no publisher-specific logic

## Related

- [Original feature doc](../../08_Epics/000_v2_foundation/004_caption_file_extended_metadata/004_feature.md) — full historical detail
- PUB-001 (caption file) — prerequisite
