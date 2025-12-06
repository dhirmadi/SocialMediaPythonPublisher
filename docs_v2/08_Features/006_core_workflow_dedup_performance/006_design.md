## Core Workflow Dedup Performance — Feature Design

## 1. Summary

- **Problem**: The core CLI workflow currently performs de-duplication by downloading candidate images from Dropbox and computing local SHA256 hashes, then comparing those hashes against a local `posted` state. For folders with many already-posted images, this leads to excessive network I/O, slow selection, and unnecessary cost, especially when the outcome is simply “no new images”.
- **Goals**:
  - Use Dropbox-native metadata (primarily `content_hash`) to perform de-duplication as early as possible, minimizing full image downloads.
  - Keep the user-facing behavior and semantics of “do not repost the same image” unchanged, including preview/dry/archival flows.
  - Evolve the posted-hash state in a backward-compatible way so that both legacy SHA256-based runs and new metadata-based runs can coexist.
- **Non-goals**:
  - Changing what counts as a “duplicate” from the user’s perspective.
  - Introducing new external data stores or cache services beyond the existing filesystem-based `posted.json`.
  - Altering publisher behavior, caption/sidecar generation, or web interface contracts.

## 2. Context & Assumptions

- **Current state**:
  - `WorkflowOrchestrator.execute`:
    - Lists images via `DropboxStorage.list_images(image_folder)` which returns a list of filenames.
    - Shuffles the list and, for each candidate, downloads the image bytes with `download_image` and computes `sha256` locally.
    - Skips images whose SHA256 appears in `utils.state.load_posted_hashes()` and selects the first unseen image.
    - On successful publish+archive, records the SHA256 via `utils.state.save_posted_hash(selected_hash)`.
  - `utils.state`:
    - Stores posted hashes in a single JSON file under the user cache dir (`posted.json`).
    - Supports legacy list format (`["hash1", "hash2"]`) and a dict format with `"hashes": [...]`.
  - `DropboxStorage`:
    - Uses the Dropbox SDK and exposes `list_images`, `download_image`, `get_temporary_link`, `get_file_metadata`, and `archive_image`.
    - `list_images` currently returns only image filenames, discarding metadata such as `content_hash`.
- **Constraints**:
  - Python `>=3.9,<4.0`.
  - No new external dependencies or long-lived services.
  - Preview mode must remain side‑effect free (no posted state changes, no archive).
  - CLI flags and web contracts must remain backward‑compatible.
- **Assumptions**:
  - Dropbox `FileMetadata.content_hash` is stable for a given file content and can be used as a logical content identifier across runs.
  - Two different filenames with identical `content_hash` should be treated as duplicates for de‑dup purposes (consistent with existing SHA256 behavior).
  - The existing SHA256-based `posted.json` may already contain a non-trivial history; we must treat it as authoritative for previously posted images.

## 3. Requirements

### Functional Requirements

1. **Metadata-based selection**  
   - When selecting an image to post (without an explicit `select_filename`), the workflow should:
     - Use Dropbox metadata (including `content_hash`) to determine which images are already posted.
     - Prefer selecting an image whose `content_hash` does not appear in the posted state, before downloading any image bytes.
2. **Efficient “no new images” handling**  
   - When all images in the configured Dropbox folder have already been posted, the workflow must:
     - Detect this condition using metadata and posted state.
     - Return the existing “No new images to post (all duplicates)” error (or equivalent wording) without downloading every file.
3. **Posted state evolution**  
   - Extend the posted-hash state to be able to store Dropbox `content_hash` values in addition to legacy SHA256 hashes.
   - Preserve and continue to understand existing state files (list or `{"hashes":[...]}`) without migration failures.
   - Ensure new runs record both the SHA256 hash (for backward compatibility) and the Dropbox `content_hash` when available.
4. **Selection determinism & compatibility**  
   - The selection algorithm must remain logically equivalent to the current behavior:
     - Only images whose content has not been posted before are eligible.
     - Randomization/shuffling order remains acceptable; no new strong ordering guarantees are required.
   - Forced selection via `--select <filename>` must continue to work and should not be blocked by dedup state.
5. **Preview/dry/debug semantics**  
   - In preview/dry/debug modes:
     - The workflow may still use metadata-based dedup for selection logic.
     - It must not persist updated posted hashes or `content_hash` values.
     - It must not archive or mutate Dropbox contents.

### Non-Functional Requirements

- **Performance**:
  - Typical image selection (including dedup) should complete in a few seconds even when most images are already posted.
  - The number of full image downloads per run should be O(1) when selecting a new image and O(0–k) when all images are duplicates (k small, ideally 0).
- **Reliability**:
  - If metadata calls fail or `content_hash` is unavailable, the system should gracefully fall back to the existing SHA256-based selection.
- **Observability**:
  - Logs should capture key counts: number of images listed, number considered as “already posted” vs “candidates”, and whether the selection used metadata or the legacy fallback.
- **Security/Privacy**:
  - No new secrets are introduced; content hashes are treated as non-sensitive identifiers.

## 4. Architecture & Design

### High-Level Approach

- Introduce a **metadata-aware listing** operation in `DropboxStorage` that returns both filenames and their Dropbox `content_hash`.
- Extend **posted state** to track both SHA256 and Dropbox `content_hash` values in a single JSON file.
- Refactor **selection logic** in `WorkflowOrchestrator.execute` to:
  - Prefer a metadata-only pass using `content_hash` to choose an unseen image.
  - Only download the bytes of the single selected candidate (or none when all are duplicates).
  - Fall back to the existing “download & hash” loop if metadata is missing/unreliable.

### Components & Responsibilities

- **`publisher_v2.services.storage.DropboxStorage`**
  - Add `async def list_images_with_hashes(self, folder: str) -> list[tuple[str, str]]`:
    - Uses `files_list_folder` and returns `(filename, content_hash)` pairs for image files.
    - Handles pagination if needed in the future (initial implementation can follow the current one‑page assumption).
  - Optionally extend `get_file_metadata` to expose `content_hash` as part of its returned dict for targeted queries (e.g., `select_filename` path).

- **`publisher_v2.utils.state`**
  - Add:
    - `def load_posted_content_hashes() -> set[str]`
    - `def save_posted_content_hash(hash_value: str) -> None`
  - State file format:
    - Continue to accept:
      - A simple list: `["hash1", "hash2"]` → interpreted as legacy SHA256 hashes.
      - A dict with `"hashes": [...]` → also legacy SHA256.
    - New extended dict format:
      ```json
      {
        "hashes": ["sha256-1", "sha256-2"],
        "dropbox_content_hashes": ["dbhash-1", "dbhash-2"]
      }
      ```
    - Both `load_*` functions should tolerate any of these forms and default to empty sets on errors.

- **`publisher_v2.core.workflow.WorkflowOrchestrator`**
  - Selection flow changes:
    - Introduce `selected_content_hash: str | None` alongside `selected_hash`.
    - When `select_filename` is **not** provided:
      1. Call `list_images_with_hashes` to obtain `(filename, content_hash)` pairs.
      2. Load posted SHA256 hashes and Dropbox `content_hash` hashes.
      3. Shuffle the list of pairs (to preserve current randomization).
      4. First pass: find a pair where `content_hash` is **not** in posted content hashes.
         - If found:
           - Set `selected_image` and `selected_content_hash`.
           - Download that single image and compute SHA256 into `selected_hash`.
         - If **none** found:
           - If metadata is complete and posted content hashes are non-empty, short‑circuit with “No new images to post (all duplicates)” **without** downloading all images.
           - If metadata appears incomplete/unusable, fall back to the legacy SHA256-based loop (downloading and hashing until an unseen SHA256 is found or exhausted).
    - When `select_filename` **is** provided:
      - Keep current behavior (download and compute SHA256) but optionally:
        - Look up `content_hash` via `list_images_with_hashes` or `get_file_metadata` to record it in posted state after archive.
  - Posted state updates:
    - After a successful archive (existing `save_posted_hash(selected_hash)` call):
      - Also call `save_posted_content_hash(selected_content_hash)` when available.
    - In preview/dry/debug modes, **do not** call the new saver.

### Data Model / Schemas (Before / After)

- **Before**:
  - `posted.json`:
    - Either a list of SHA256 hashes or a dict `{"hashes":[...sha256...]}`.
  - Workflow selection uses only SHA256 from `posted.json`.
- **After**:
  - `posted.json`:
    - May be:
      - A legacy list.
      - A dict with:
        - `"hashes": [sha256...]`
        - `"dropbox_content_hashes": [content_hash...]` (optional).
  - `utils.state` continues to expose `load_posted_hashes()` / `save_posted_hash()` for SHA256 and adds dedicated helpers for Dropbox `content_hash`.
  - `WorkflowResult` remains unchanged; new fields are internal only.

### Error Handling & Fallbacks

- If `list_images_with_hashes` fails or returns entries without `content_hash`:
  - Log an INFO/DEBUG event indicating fallback to legacy dedup.
  - Use the current per-image download+SHA256 loop.
- If `save_posted_content_hash` fails to write:
  - Swallow the exception (best-effort semantics), mirroring `save_posted_hash`.
- If state parsing fails due to unexpected JSON:
  - Treat as empty sets and continue; do **not** crash the workflow.

### Security, Privacy, Compliance

- No additional sensitive data is stored; only non‑reversible content hashes.
- Existing security guidelines (secrets via env/INI, no raw tokens in logs) remain unchanged.

## 5. Detailed Flow

### Normal Run with New Images

1. CLI invokes `WorkflowOrchestrator.execute`.
2. Orchestrator lists `(filename, content_hash)` pairs via `list_images_with_hashes`.
3. Loads posted SHA256 and content hashes from `posted.json`.
4. Shuffles candidates and finds the first pair whose `content_hash` is not in the posted set.
5. Downloads that single image, computes SHA256, and proceeds with analysis, captioning, publishing, and archiving.
6. On successful archive:
   - Saves SHA256 via `save_posted_hash`.
   - Saves Dropbox `content_hash` via `save_posted_content_hash`.

### Run with Only Already-Posted Images

1. Orchestrator lists `(filename, content_hash)` pairs.
2. All `content_hash` values are found in posted content hashes.
3. No candidate is selected; orchestrator:
   - Logs that all candidates are duplicates by metadata.
   - Returns a `WorkflowResult` with `success=False` and `error="No new images to post (all duplicates)"` (existing wording), without downloading any images.

### Preview / Dry Run

1. Selection uses the same metadata-aware flow to avoid unnecessary downloads where possible.
2. After analysis/caption/preview output:
   - No calls to `save_posted_hash` or `save_posted_content_hash`.
   - No archive; Dropbox contents remain unchanged.

## 6. Rollout & Ops

- **Feature flags / Config**:
  - No new user-facing flags; metadata-based dedup is the new default.
  - Internally, we may keep a small, local “fallback to legacy” branch controlled by runtime checks (e.g., missing `content_hash`).
- **Migration / Backfill**:
  - No mandatory migration; existing `posted.json` files are valid.
  - As new runs archive images, both SHA256 and Dropbox `content_hash` entries will gradually accumulate.
- **Monitoring & Logging**:
  - Add structured logs such as:
    - `dedup_selection_start` / `dedup_selection_complete` with counts:
      - `images_total`, `images_already_posted`, `images_candidates`, `used_metadata: bool`, `fallback_legacy: bool`.
  - These can be correlated via the existing `correlation_id` in the workflow logs.

## 7. Risks & Alternatives

- **Risks**
  - **Dropbox `content_hash` semantics change**: could lead to false negatives/positives in dedup.
    - Mitigation: retain SHA256 state and ability to fall back; log clearly when metadata-based dedup is used.
  - **State format drift**: incorrectly evolving `posted.json` could cause duplicates or over-aggressive filtering.
    - Mitigation: additive, backward-compatible JSON structure; robust parsing with tests for legacy and new formats.
  - **Partial metadata**: some entries might be missing `content_hash`.
    - Mitigation: detect and fall back to legacy SHA256-only flow for those runs.
- **Alternatives considered**
  - Adding a separate “posted_content_hashes.json”:
    - Rejected to avoid extra files and keep state co-located.
  - Introducing a DB table for posted images:
    - Rejected per repo constraints (no new persistent stores).


