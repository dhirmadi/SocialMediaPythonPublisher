<!-- 08_01_Feature_Request/004_caption-file-extended-metadata.md -->

# Caption File Extended Metadata

**ID:** 004  
**Name:** caption-file-extended-metadata  
**Status:** Proposed  
**Date:** 2025-11-09  
**Author:** Evert  

## Summary
Add a structured, comment-prefixed metadata block beneath the first-line Stable Diffusion caption in per-image `.txt` files. The first line remains the pure caption for training compatibility; the appended block captures identity, versioning, analysis context, and artistic descriptors for richer dataset curation, querying, and automation. This preserves existing workflows while enabling downstream analytics and iterative re-captioning.

## Problem Statement
Today, caption files contain only a single training caption, losing valuable context about image identity, analysis provenance, artistic attributes, and moderation signals. This limits dataset searchability, deduplication accuracy, traceability of model versions, and the ability to segment or refine data over time without external databases. A backward-compatible way to embed structured context alongside the caption is needed.

## Goals
- Preserve training compatibility by keeping the caption as the first line only.
- Append a structured, comment-prefixed metadata block with identity, versioning, and context.
- Enable dataset querying, segmentation, deduplication, and automated curation without breaking current pipelines.

## Non-Goals
- Changing the caption semantics or training ingestion of the first line.
- Embedding explicit sexual content; metadata remains PG‑13, artistic/contextual only.
- Replacing external databases; this is a sidecar enrichment, not a full catalog system.
- Altering publisher behavior or platform-specific posting flows.

## Users & Stakeholders
- Primary users: Dataset curators, ML/Research engineers, content creators/editors.
- Stakeholders: SocialMediaPythonPublisher maintainers, MLOps/infrastructure, compliance reviewers.

## User Stories
- As a curator, I want metadata about pose, lighting, and style, so that I can segment and filter images for targeted training runs.
- As an ML engineer, I want model and schema versions recorded, so that I can trace caption provenance and compare model revisions.
- As an operator, I want file identity and hashes recorded, so that I can deduplicate and track revisions across archives.
- As a reviewer, I want moderation tags separated from the caption, so that training text remains clean while enabling filtering.

## Acceptance Criteria (BDD-style)
- Given a generated `sd_caption`, when writing `<image>.txt`, then the first line is exactly the `sd_caption` with no trailing inline metadata.
- Given caption file generation, when metadata is appended, then all metadata lines are prefixed with `# ` and an initial `# ---` separator appears on the next line after the caption.
- Given metadata output Phase 1, when files are written, then the block includes: `image_file`, `dropbox_file_id` (if available), `dropbox_rev` (if available), `sha1` (or repo-standard hash), `created` (UTC ISO8601), `sd_caption_version`, `model_version`.
- Given metadata output Phase 2 (flagged), when enabled, then the block additionally includes contextual fields: `lighting`, `pose`, `materials`, `art_style`, `tags` (JSON array), `moderation` (JSON array).
- Given preview or dry-run mode, when generating outputs, then no files are created or mutated; preview prints show the full caption and metadata block.
- Given reprocessing of the same image, when writing `<image>.txt`, then the file is overwritten atomically and archived side-by-side with the image on move.
- Given training pipelines that read only the first line, when this change is deployed, then training outcomes remain unaffected.
- Given metadata fields are unavailable, when writing the block, then missing fields are omitted rather than populated with null-like placeholders.

## UX / Content Requirements
- File: `<image_basename>.txt`
- Line 1: Pure `sd_caption` only.
- Separator: `# ---` on line 2.
- Metadata: subsequent `# key: value` lines; arrays encoded as JSON arrays; keys lower_snake_case; times in UTC ISO8601.
- Example:
  ```
  a fine-art figure study, standing pose, low-key lighting, minimalist studio

  # ---
  # image_file: IMG_1837.jpg
  # dropbox_file_id: id:XXXXXXXXXX
  # dropbox_rev: XXXXXXXX
  # sha1: 349a9c91ce52...
  # created: 2025-02-18T11:32:01Z
  # sd_caption_version: v1.0
  # model_version: gpt-5-vision-2025-02
  # lighting: low-key directional softbox
  # pose: standing, relaxed arms, torso angled
  # materials: rope body-form art styling
  # art_style: fine-art figure study
  # tags: ["minimalist","shadow-play","studio portrait","body-form art"]
  # moderation: ["nudity"]
  ```
- Accessibility/Localization: N/A for file format; ensure ASCII-compatible keys and stable separators.

## Technical Constraints & Assumptions
- Must be fully backward-compatible with existing CLI flags and behavior; first line unchanged.
- Comment prefix `# ` ensures metadata is ignored by simple line-1 readers; no trailing spaces.
- Phase-gated rollout: Phase 1 on by default; Phase 2 behind a config flag (e.g., `captionfile.extended_metadata=true`), default off.
- Respect preview/dry-run: no side effects; use existing preview utilities.
- Conform to V2 architecture: implement in existing caption file writer path; no publisher-specific logic.
- Avoid blocking calls in async paths; reuse existing async services and rate limiter.
- No secrets logged; redact any IDs if needed in logs.

## Dependencies & Integrations
- Dropbox: file identity fields (`id`, `rev`) and archive move behavior must remain consistent.
- OpenAI: model name/version used for analysis/captioning recorded in metadata.
- Existing utilities: hashing, preview, logging, and workflow orchestrator hooks.

## Data Model / Schema
- Sidecar format only (no DB changes).
- Phase 1 keys (baseline):
  - `image_file` (str), `dropbox_file_id` (str, optional), `dropbox_rev` (str, optional), `sha1` (str), `created` (UTC ISO8601), `sd_caption_version` (str), `model_version` (str)
- Phase 2 keys (extended, optional):
  - `lighting` (str), `pose` (str), `materials` (str), `art_style` (str), `tags` (JSON array[str]), `moderation` (JSON array[str])
- Validation: omit unavailable fields; no nulls; stable key spelling; schema version implied via `sd_caption_version`.

## Security / Privacy / Compliance
- Do not include secrets or access tokens.
- Metadata content must remain PG‑13 and artistic/contextual only; no explicit sexual descriptors.
- File permissions consistent with temp and output file security (e.g., 0600 where applicable).
- Structured logs must redact any sensitive identifiers per repo logging rules.

## Performance & SLOs
- Overhead: O(1) per image; negligible compared to AI calls.
- I/O: atomic write/replace to avoid partial files.
- Target P95 caption file write latency: ≤10 ms beyond current baseline (local FS).

## Observability
- Metrics:
  - `captionfile.metadata_written.count`
  - `captionfile.extended_metadata.enabled.count`
  - `captionfile.write.errors.count`
- Logs & events:
  - JSON log with image basename, fields included, phase flag state (no secrets).
- Dashboards/alerts: TODO (add counts and error rates over time).

## Risks & Mitigations
- Some trainers may not ignore commented lines beyond line 1 — Mitigation: keep metadata strictly after line 1; provide a config to disable metadata entirely if needed.
- Field availability varies (Dropbox IDs) — Mitigation: omit missing fields; document optionality.
- Schema drift over time — Mitigation: version via `sd_caption_version`; document changes in docs.
- Content drift into explicit territory — Mitigation: enforce PG‑13 filters; add validation checks.

## Open Questions
- Should the metadata block be YAML-valid for future parsing? — Proposed answer: Yes, comment-prefixed YAML-like lines with JSON arrays accepted; keep simple.
- Expose a CLI flag to disable metadata entirely? — Proposed answer: Yes, `--no-caption-metadata` to hard-disable.
- Include SHA256 vs SHA1? — Proposed answer: Prefer SHA256 to match repo dedup standard; align with existing utils.
- How to handle Windows line endings if any? — Proposed answer: Normalize to `\n`.

## Milestones
- M1: Discovery/Design — exit: schema keys finalized; config flags defined; docs drafted.
- M2: Implementation — exit: Phase 1 default-on implemented; tests pass; preview output updated; Phase 2 behind flag implemented.
- M3: Validation/Rollout — exit: Docs published; sample outputs verified; optional flag behaviors validated; monitoring added.

## Definition of Done
- Tests cover file creation, overwrite behavior, preview output, archive move co-location, and opt-in Phase 2.
- Docs updated under `docs_v2/08_Features/` and configuration documentation.
- Backward compatibility preserved; default behavior safe; flags honored.
- Structured logs and metrics emitted; no linter/type errors.

## Appendix: Source Synopsis
- Proposal to append a rich, comment-prefixed metadata block under the first-line caption to maintain training compatibility.
- Metadata to include identity, versioning, creation timestamps, artistic context (pose, lighting, materials, style), tags, and moderation.
- Two-phase rollout: Phase 1 (identity/version/timestamps), Phase 2 (contextual fields) with a feature flag.
- Emphasis on PG‑13 artistic descriptors, backward compatibility, and future-proofing for dataset analytics and automation.


