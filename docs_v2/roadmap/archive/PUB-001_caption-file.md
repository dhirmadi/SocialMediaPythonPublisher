# PUB-001: Caption File

| Field | Value |
|-------|-------|
| **ID** | PUB-001 |
| **Category** | AI |
| **Priority** | INF |
| **Effort** | M |
| **Status** | Done |
| **Dependencies** | — |

## Problem

The image-analysis workflow produces JSON for social media purposes only. Creators need Stable-Diffusion-ready caption files for model training and fine-art photography labels. Existing behavior (description, mood, tags, nsfw, safety_labels) must remain unchanged.

## Desired Outcome

Alongside the existing JSON output, extract an additional structured caption string optimized for fine-art photography training and save it as a `.txt` file next to the image. The caption includes pose description, styling/material cues, lighting, and artistic photography terms. The file is used for model-training labels and does not interfere with the social media captioning pipeline.

## Scope

- New `sd_caption` field in vision analysis JSON
- `.txt` file creation: same directory and basename as image (`image.jpg` → `image.txt`)
- Content: single-line `sd_caption` only; overwrite if exists
- Caption structure: PG-13, artistic (pose, styling, lighting, fine-art descriptors)
- Config flags: `sd_caption_enabled`, `sd_caption_single_call_enabled`
- Caption file moves with image when archived

## Acceptance Criteria

- AC1: Existing social-media JSON output remains identical and untouched
- AC2: New `sd_caption` field added to the JSON response
- AC3: A `.txt` file is created for each image containing only the SD caption
- AC4: Caption includes pose + styling + lighting + fine-art descriptors
- AC5: Re-processing an image safely overwrites the caption file
- AC6: When the image is moved to the archive, so is the caption file

## Implementation Notes

- Feature enabled by default; controlled via `[openAI]` flags
- Optional prompt/model overrides for fine control
- Preview mode displays `sd_caption` but performs no uploads or moves
- Stories: implementation, sidecars-as-AI-cache, sd-caption AI service integration, sidecar-not-found fast-path

## Related

- [Original feature doc](../../08_Epics/000_v2_foundation/001_caption_file/001_feature.md) — full historical detail
