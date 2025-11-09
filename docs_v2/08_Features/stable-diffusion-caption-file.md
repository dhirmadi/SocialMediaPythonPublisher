# Stable Diffusion Caption File

**Feature ID:** stable-diffusion-caption-file  
**Status:** Shipped  
**Date Completed:** TODO  
**Code Branch / PR:** feature/captionfile (PR: TODO)  

## Summary
Adds a Stable‑Diffusion‑ready caption alongside existing analysis without changing current outputs. The system generates an `sd_caption` string and writes a `.txt` sidecar next to each image, overwriting on reprocessing and moving with the image on archive. Behavior remains backward‑compatible; preview mode displays the full sidecar (first‑line `sd_caption` plus a commented metadata block) with no side effects.

## Goals
- Add `sd_caption` to analysis output without modifying existing fields/semantics.
- Create `<image>.txt` beside the image containing:
  - Line 1: the `sd_caption` only (training‑safe)
  - Below: a `#`‑prefixed metadata block with identity/version fields (Phase 1)
  - Optional: extended contextual metadata (Phase 2) behind a flag
- Archive the `.txt` sidecar together with the image.
- Enforce PG‑13, fine‑art phrasing with pose, styling/materials, lighting, and mood.
- Prefer single caption‑model call returning `{caption, sd_caption}`; fall back to legacy.
- Show full sidecar in preview; preview remains side‑effect free.
- Keep failures non‑blocking; log and continue.

## Non-Goals
- Changing description/mood/tags/nsfw/safety_labels semantics.
- Modifying publisher‑specific formatting or logic.
- Introducing database storage.
- Generating the sidecar after archive (must exist pre‑archive).

## User Value
Enables immediate use of published photos for model training by emitting high‑quality, PG‑13 fine‑art Stable Diffusion captions as sidecar files, while leaving social publishing unchanged. This streamlines dataset creation and reduces manual labeling effort.

## Technical Overview
- Core flow:
  - Orchestrator → Vision analysis (unchanged) → Single caption call returns `{caption, sd_caption}` → Build sidecar content (`sd_caption` + commented metadata) → Write sidecar `.txt` → Publish (existing) → Archive image and sidecar together.
- Key components touched:
  - `services/ai.py`: `CaptionGeneratorOpenAI.generate_with_sd`; `AIService` helper to use it.
  - `core/workflow.py`: Integrates `sd_caption` path, builds metadata, writes sidecar, includes preview output.
  - `services/storage.py`: `write_sidecar_text`; `get_file_metadata(id, rev)`; archive moves sidecar with image.
  - `utils/captions.py`: `build_metadata_phase1/phase2`, `build_caption_sidecar`.
  - `utils/preview.py`: `print_caption_sidecar_preview`.
  - `config/schema.py`, `config/loader.py`: Add feature flags/model/prompt options and captionfile flag.
  - `core/models.py`: Add `sd_caption` to `ImageAnalysis`.
- Flags / config:
  - `[openAI] sd_caption_enabled=true`
  - `[openAI] sd_caption_single_call_enabled=true`
  - Optional: `sd_caption_model`, `sd_caption_system_prompt`, `sd_caption_role_prompt`
  - `[CaptionFile] extended_metadata_enabled=false` (Phase 2 opt‑in)
- Data model updates:
  - `ImageAnalysis.sd_caption: Optional[str] = None` (add‑only).
- External API usage:
  - OpenAI Chat Completions with `response_format={"type":"json_object"}` for `{caption, sd_caption}`.
  - Dropbox API for uploading `.txt` sidecar and moving it on archive.
  - Existing async rate limiting and retries via `AsyncRateLimiter` and `tenacity`.

## Implementation Details
- Key functions/classes:
  - `CaptionGeneratorOpenAI.generate_with_sd(analysis, spec) -> {"caption": str, "sd_caption": str}`
  - `AIService.create_caption_pair(...) -> (caption: str, sd_caption: Optional[str])`
  - `DropboxStorage.write_sidecar_text(folder, filename, text) -> None`
  - `DropboxStorage.archive_image(...)` updated to also move `<filename>.txt` if present
  - `WorkflowOrchestrator.execute(...)` integration to set `analysis.sd_caption`, write sidecar, include in preview
  - `preview.print_vision_analysis(...)` updated to show `sd_caption`
- Migrations:
  - None (add‑only config/fields).
- Error handling:
  - Strict JSON parsing with fallback to legacy `generate()` if invalid; omit `sd_caption` on failure.
  - Sidecar upload/move failures are logged and non‑fatal; workflow continues.
  - Archive attempts to move sidecar; logs warn if missing.
- Performance + reliability:
  - Single‑call design avoids extra LLM cost/latency; adheres to existing rate limits and retry budgets.
  - Sidecar upload is small; bounded backoff on transient Dropbox errors.
- Security / privacy:
  - No new secrets or scopes; secrets from environment/INI.
  - PG‑13 enforced via prompt; optional sanitization guidance in design.
  - Preview path performs no side effects.

## Testing
- Unit tests:
  - `generate_with_sd` strict JSON structure, PG‑13 enforcement, fallback behavior.
  - `write_sidecar_text` path/name correctness, overwrite semantics, error handling.
  - Archive moves both image and sidecar; no crash when sidecar missing.
  - Orchestrator sets `sd_caption` and triggers sidecar write when enabled.
  - `build_caption_sidecar` formatting and omission of missing fields.
- Integration:
  - Dry‑run with mocked OpenAI/Dropbox verifies sidecar creation and archive call.
  - Preview prints the full sidecar and does not publish or archive.
- E2E:
  - Preview then live: preview shows `sd_caption`; live moves sidecar with image; preview has no side effects.
  - Sidecar content includes `# ---` separator and Phase 1 fields; Phase 2 fields when enabled.

## Rollout Notes
- Feature flags:
  - `sd_caption_enabled` (default: true)
  - `sd_caption_single_call_enabled` (default: true)
- Monitoring / logs:
  - `sd_caption_start|complete|error`
  - `sidecar_upload_start|complete|error`
  - `sidecar_archive_start|complete|warn_missing`
- Backout strategy:
  - Disable flags to revert to legacy behavior (no `sd_caption`, no sidecar write); no data migration needed.

## Artifacts
- Design doc: docs_v2/08_Features/08_02_Feature_Design/001_captionfile_design.md
- Plan: docs_v2/08_Features/08_03_Feature_plan/001_captionfile_design_plan.yaml
- PR: TODO

## Final Notes
- Edge cases:
  - Empty/invalid `sd_caption`: skip file creation; continue.
  - Missing/forbidden folder for sidecar: log error; continue.
  - Archive when sidecar missing: move image only; log at INFO/DEBUG.
  - Potential autorename divergence in Dropbox archive: low risk; acceptable as per design.
- Future improvements:
  - Optionally compute final archived image name first to guarantee sidecar name match.
  - Expose success/error counters and latency metrics for observability.


