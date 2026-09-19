---
name: caption-sidecar-schema
description: >-
  Stable Diffusion caption file (.txt) and extended-metadata sidecar schema for
  publisher_v2, with worked examples of the exact file format, field list, and
  phase-1/phase-2 metadata block. Use when editing caption generation, sidecar
  files, vision analysis output, or metadata fields, or when adding new fields to
  ImageAnalysis or the caption writer.
---

# Caption & sidecar schema (worked examples)

The enforcement rule (do not rename/repurpose fields) lives in
`.cursor/rules/30-caption-sidecar-features.mdc` / `.claude/rules/captions-sidecars.md`.
This skill is the worked reference for what the actual output looks like.

## Vision analysis JSON (PUB-003)

Existing fields are untouched; new fields are optional and `null`/`[]` when unknown:

```json
{
  "description": "Woman in flowing red dress on a rain-soaked city street at dusk.",
  "mood": "moody, cinematic",
  "tags": ["portrait", "urban", "night"],
  "nsfw_flags": [],
  "safety_labels": [],
  "sd_caption": "A woman in a flowing red dress standing on a rain-soaked city street at dusk, cinematic lighting, shallow depth of field",
  "subject": "woman in red dress",
  "style": "cinematic portrait",
  "lighting": "dusk, wet-street reflections, cool rim light",
  "camera": null,
  "clothing_or_accessories": "flowing red dress",
  "aesthetic_terms": ["cinematic", "moody", "shallow depth of field"],
  "pose": "standing, three-quarter turn",
  "composition": "rule of thirds, subject left of frame",
  "background": "rain-soaked city street, dusk",
  "color_palette": "red, deep blue, amber highlights"
}
```

- `description` stays ≤ 30 words.
- Any field the model can't determine is `null` (or `[]` for `aesthetic_terms`/`tags`), never
  omitted or filled with a placeholder string.

## Caption file: `<image>.txt` (PUB-001 + PUB-004)

Same directory and basename as the image (`sunset-portrait.jpg` → `sunset-portrait.txt`).
Line 1 is the pure `sd_caption` — training pipelines that only read line 1 must never see
anything else there. Metadata (if `captionfile.extended_metadata` config is on) is appended
below a `# ---` separator, one `# `-prefixed line per field:

```text
A woman in a flowing red dress standing on a rain-soaked city street at dusk, cinematic lighting, shallow depth of field
# ---
# image_file: sunset-portrait.jpg
# dropbox_file_id: id:AbCdEfGhIjKlMnOp
# dropbox_rev: 5f3e2a1
# sha1: 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b
# created: 2026-09-18T14:32:07Z
# sd_caption_version: 1
# model_version: gpt-4.1
# lighting: dusk, wet-street reflections, cool rim light
# pose: standing, three-quarter turn
# materials: flowing red dress
# art_style: cinematic portrait
# tags: ["portrait", "urban", "night"]
# moderation: []
```

- Phase 1 fields (`image_file`, `dropbox_file_id`, `dropbox_rev`, `sha1`, `created`,
  `sd_caption_version`, `model_version`) are on by default.
- Phase 2 fields (`lighting`, `pose`, `materials`, `art_style`, `tags`, `moderation`, plus
  `subject`/`camera`/`composition`/`background`/`color_palette`/`aesthetic_terms` when
  available) are behind the `captionfile.extended_metadata` flag.
- A field with no value is **omitted entirely** from the block — never written as
  `# lighting: null` or `# lighting: `.
- Overwrite atomically on reprocessing; the caption file moves with the image on archive.
- In preview/dry-run: print the full caption + metadata block, write nothing to disk.

## Adding a new field

1. Add it to `ImageAnalysis` as **optional** — never repurpose an existing field name.
2. Decide Phase 1 (always on) vs. Phase 2 (behind `captionfile.extended_metadata`).
3. Update the archived specs it extends (`docs_v2/roadmap/archive/PUB-003_*.md` and/or
   `PUB-004_*.md`) with a dated amendment note, or open a new roadmap item if the change is
   significant enough to warrant its own ACs.
4. Add/update tests under `publisher_v2/tests/**caption**` / `**sidecar**` covering: field
   present, field absent (omitted, not null), and preview mode (no file write).
