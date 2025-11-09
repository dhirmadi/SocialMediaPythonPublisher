## Stable Diffusion Caption File — Feature Design

## 1. Summary

- **Problem**: We need to output, alongside the existing social-media JSON analysis, a Stable-Diffusion-ready caption and persist it as a `.txt` sidecar file next to the image. Existing outputs/behavior must remain unchanged.
- **Goals**: 
  - Add `sd_caption` to the in-memory analysis result and to any JSON surfaced in preview/debug, without modifying existing fields.
  - Create/overwrite a `.txt` file (`image.jpg` → `image.txt`) containing only the `sd_caption`.
  - When archiving an image, move its sidecar `.txt` with it.
  - Avoid extra LLM cost by generating both the social caption and `sd_caption` in a single caption model call.
- **Non-goals**:
  - Changing existing description/mood/tags/nsfw/safety_labels semantics.
  - Modifying publisher logic or platform-specific formatting.
  - Introducing database storage.

### Assumptions & Open Questions
- **Assumptions**:
  - Images are stored and archived in Dropbox using existing `DropboxStorage` methods.
  - Sidecar `.txt` creation should occur after analysis is available and before archiving/publishing completes (overwriting if exists).
  - PG‑13 constraints are enforced via prompt and light, deterministic sanitization.
  - If SD caption generation fails, the pipeline should still succeed with existing behavior (best-effort, non-blocking).
  - `sd_caption` should be visible in preview output (non-blocking for publish).
- **Open Questions**:
  - Should SD caption generation be guarded by a config flag (e.g., `sd_caption_enabled`), and default to enabled? Proposed: Yes, default enabled.
  - Which model to use for SD caption generation? Proposed: reuse `caption_model` unless `sd_caption_model` is provided.
  - Should we expose the `.txt` creation step in logs at INFO level or DEBUG? Proposed: INFO on success/failure once per image.

## 2. Context & Assumptions

- **Current state**:
  - Vision analysis and caption generation are handled in `publisher_v2/services/ai.py` via `VisionAnalyzerOpenAI` and `CaptionGeneratorOpenAI`. The `WorkflowOrchestrator` coordinates analysis, caption generation, and publishing. Archival occurs via `DropboxStorage.archive_image`.
  - The analysis JSON currently includes: `description`, `mood`, `tags`, `nsfw`, `safety_labels`.
  - No sidecar text file is produced today, and archive only moves the image file.
- **Constraints**:
  - Backwards compatibility: all existing outputs must remain identical; add-only change.
  - Rate limiting: reuse existing `AsyncRateLimiter` behavior.
  - Dropbox: must create the `.txt` in the same folder and move it with the image upon archive.
- **Dependencies**:
  - OpenAI API availability and configured keys.
  - Dropbox API for file upload/move.

## 3. Requirements

- **Functional Requirements**
  1. Do not modify existing JSON fields or change semantics/values.
  2. Add `sd_caption` (single sentence) to analysis output object.
  3. Generate a `.txt` file with only `sd_caption` content (one line) next to the image; overwrite if exists.
  4. Ensure PG-13, fine‑art terms; include pose, styling/materials, lighting/mood.
  5. When archiving an image, move the `.txt` sidecar alongside it (autorename behavior consistent with image move).
  6. If SD caption generation fails, continue pipeline without blocking publishing; log error.
  7. In preview mode, display `sd_caption` in the preview output (non-blocking).
  8. Prefer a single caption-model call that returns both `caption` and `sd_caption`; fall back to legacy single-caption call if disabled.

- **Non-Functional Requirements**
  - Performance: Avoid extra LLM calls by default; keep within existing retry/timeout budgets.
  - Reliability: Retries align with tenacity settings; failures are non-fatal with neutral fallbacks.
  - Cost: Single-call design minimizes incremental cost; feature can be disabled via config.
  - Observability: Log start/end and failures for SD caption generation and sidecar upload/move.
  - Security/Privacy: No PII; safe prompts; adhere to PG-13.

## 4. Architecture & Design

- **Proposed Architecture (diagram description)**
  - Orchestrator obtains temporary link → Vision analysis (unchanged) → Caption model single call returns `{caption, sd_caption}` (updated) → Sidecar `.txt` upload (new) → Publish (existing) → Archive image + sidecar (updated).

- **Components & Responsibilities**
  - `CaptionGeneratorOpenAI.generate_with_sd(analysis, spec)` (updated): Return strict JSON with both `caption` and `sd_caption` in one call. Keep existing `generate()` unchanged for backward compatibility.
  - `AIService` (updated): Provide a helper to use `generate_with_sd` when enabled; otherwise fall back to `generate()`.
  - `DropboxStorage.write_sidecar_text(folder, filename, text)` (new): Upload `.txt` sidecar for `filename` to `folder`, overwriting if exists.
  - `DropboxStorage.archive_image_with_sidecar(...)` or enhancement to `archive_image` (updated): Move both image and its `.txt` sidecar if present.
  - `WorkflowOrchestrator` (updated): Use single-call caption path, write sidecar, include `sd_caption` in preview.

- **Data Model / Schemas (before/after)**
  - Before: `ImageAnalysis` has `description: str`, `mood: str`, `tags: List[str]`, `nsfw: bool`, `safety_labels: List[str]`.
  - After: add `sd_caption: Optional[str] = None` (add-only, backward-compatible).

- **API/Contracts (request/response; versioning)**
  - No external API change. Internally, `ImageAnalysis` gains `sd_caption`. Preview JSON output (if any) includes `sd_caption` when present.
  - `CaptionGeneratorOpenAI` adds `generate_with_sd` returning a JSON object: `{"caption": str, "sd_caption": str}` while preserving `generate()` string return for legacy paths.
  - Storage contract: new sidecar `.txt` named after image base name.

- **Error Handling & Retries**
  - Caption single call: strict JSON enforced; on JSON decode error, fallback to extracting `caption` and omit `sd_caption`; retry with softened neutral prompt if model refuses.
  - Sidecar upload: retry on transient Dropbox errors; on final failure, log but do not fail publish.
  - Archive: attempt to move sidecar; if missing or move fails, log warning; do not fail workflow.

- **Security, Privacy, Compliance**
  - Enforce PG‑13 via prompt constraints and optional sanitization (strip explicit terms). Use neutral terminology (“figure study”, “rope art”, “kinbaku-inspired ropework”), explicitly forbid explicit sexual terms.
  - No additional secrets or scopes beyond existing OpenAI and Dropbox creds.

## 5. Detailed Flow

1. Orchestrator gets temporary link and runs vision analysis (unchanged).
2. Orchestrator invokes `CaptionGeneratorOpenAI.generate_with_sd(analysis, spec)` which returns strict JSON `{caption, sd_caption}` in a single call.
   - System prompt: fine‑art photography; PG‑13; neutral vocabulary; return strict JSON object with both fields.
   - If refusal or invalid JSON: retry with safer neutral phrasing; on final failure, fall back to `generate()` and omit `sd_caption`.
3. On success: set `analysis.sd_caption` and call `DropboxStorage.write_sidecar_text(image_folder, image_name, sd_caption)` which uploads `image.txt` with overwrite semantics.
5. Publish as usual.
6. On archive: call updated storage method to move both `image` and `image.txt` to the archive folder (autorename behavior consistent).
7. In preview: include `sd_caption` field in preview output.

### Edge cases
- SD caption generation empty/invalid: skip file creation; continue.
- Sidecar upload forbidden/missing folder: skip, log error.
- Archive when sidecar does not exist: move image only; log at DEBUG/INFO.

## 6. Rollout & Ops

- **Feature flags, Config**
  - `sd_caption_enabled` (bool, default: true).
  - `sd_caption_single_call_enabled` (bool, default: true) — use the single-call `{caption, sd_caption}` path.
  - `sd_caption_model` (optional; default to `caption_model` if unset).
  - `sd_caption_system_prompt`, `sd_caption_role_prompt` (optional; ship safe defaults with neutral, non-explicit vocabulary).

- **Migration/Backfill plan**
  - No data migration. New optional fields/config with defaults ensure backwards compatibility.
  - Existing runs will start producing sidecar files where enabled.

- **Monitoring, Logging, Dashboards, Alerts**
  - Logs: `sd_caption_start`, `sd_caption_complete` (length), `sd_caption_error`.
  - Logs: `sidecar_upload_start|complete|error`, `sidecar_archive_start|complete|warn_missing`.
  - Optional metric counters for success/failure counts.

- **Capacity/Cost estimates**
  - No additional LLM calls in the single-call path (same cost as current caption generation).
  - Dropbox overhead: one small text upload + optional move.

## 7. Testing Strategy

- **Unit Tests**
  - `CaptionGeneratorOpenAI.generate_with_sd`: strict JSON structure; PG‑13 enforcement; graceful fallback when refused/invalid.
  - `DropboxStorage.write_sidecar_text`: correct path/name; overwrite behavior; error handling.
  - Archive method: moves both image and sidecar when present; no crash when sidecar missing.
  - `WorkflowOrchestrator`: when enabled, sets `analysis.sd_caption` and calls sidecar write.

- **Integration Tests**
  - Dry-run with mocked OpenAI/Dropbox verifying sidecar creation and archive call on success.
  - Preview mode shows `sd_caption` and does not publish.

- **E2E (manual/smoke)**
  - Run with real creds on a test folder; inspect `.txt` beside image; move to archive with both files.

- **Performance**
  - Measure added latency p50/p95; verify retries bounded and non-blocking on failure.

- **Test Cases mapped to Acceptance Criteria**
  - Existing JSON remains identical: snapshot tests of analysis fields.
  - `sd_caption` present and single-sentence style.
  - `.txt` created/overwritten with only the SD caption.
  - Re-processing overwrites `.txt` safely.
  - Archiving moves both files.

## 8. Risks & Alternatives

- **Risks with mitigations**
  - JSON compliance risk in single-call response → enforce `response_format={"type":"json_object"}` and add robust parse fallback.
  - Prompt drift producing non-PG‑13 content → tighten system prompt; defensive sanitization for common explicit terms; retries with neutral phrasing.
  - Archive drift if Dropbox autorename changes target name → move sidecar first using same base name, or compute final archived name and apply to sidecar (see implementation note below).

- **Alternatives considered**
  - Two-call approach (caption + sd_caption separately): increases latency and cost; retained as fallback only.
  - Single-call vision JSON including `sd_caption`: rejected to avoid changing existing analysis prompt/contract.
  - Generating sidecar after archive: rejected; file must sit next to image pre-archive and then move together.

## 9. Work Plan

- **Milestones & Tasks**
  1. Add `sd_caption` to `ImageAnalysis` dataclass (optional field). 
  2. Add `generate_with_sd` to `CaptionGeneratorOpenAI` returning strict JSON; update `AIService` to use it when enabled.
  3. Add `sd_caption_enabled`, `sd_caption_single_call_enabled`, `sd_caption_model`, and prompt config with safe defaults.
  4. Implement `DropboxStorage.write_sidecar_text` (overwrite semantics).
  5. Update archive flow to move sidecar with image. Implementation note: capture the destination name returned by `files_move_v2` for the image and compute/move sidecar path to match, or move sidecar by constructing target name using the same base (accepting autorename divergence as low risk).
  6. Orchestrator integration: use single-call caption path and sidecar write; include in preview output.
  7. Logging instrumentation and docs.
  8. Tests: unit + integration + preview snapshot updates.

- **Definition of Done**
  - All acceptance criteria met.
  - Configurable and backward-compatible; defaults preserve behavior if disabled.
  - Tests added/updated and passing.
  - Documentation updated (README/docs_v2), including config keys and preview behavior.

## 10. Appendices

- **Example Prompts**

```text
System: You are a fine‑art photography assistant. Produce a single-sentence Stable Diffusion training caption.
It must be PG‑13 and artistic, and include: pose description, styling/materials, lighting & mood, and fine‑art terms.
Output only the caption, no quotes.

User: description='{analysis.description}', mood='{analysis.mood}', tags={analysis.tags}. Keep concise.
```

- **Example Sidecar Content**

```text
low-key studio figure study, single person, female, brown hair, slender figure, rope body-form art styling, standing pose with relaxed arms, dramatic side lighting, fine-art portrait photograph
```

- **Example Storage Behavior**
  - Image: `/ImagesToday/image.jpg` → Sidecar: `/ImagesToday/image.txt`
  - Archive: `/ImagesToday/archive/image.jpg` and `/ImagesToday/archive/image.txt`


