## Performance Review — Social Media Publisher V2

**Date**: 2025-11-20  
**Author**: Senior Architect (AI assistant)  
**Scope**: End‑to‑end performance for CLI workflow and FastAPI web interface.

---

### 1. Current Performance Shape (High Level)

- **Dominant latency sources**:
  - External services: **Dropbox** (`list_images`, `download_image`, `get_temporary_link`, `archive_image`) and **OpenAI** (`analyze`, `generate`, `generate_with_sd`).
- **Workflow structure**:
  - Rough path: `list_images → download + hash many images → temp file → vision → caption(+sd) → sidecar → parallel publish → archive`.
- **Web behavior**:
  - `/api/images/random` and `/api/images/{filename}/analyze` call Dropbox and OpenAI even when sidecars already exist and when a cheaper metadata read would suffice.
- **NFR targets** (from `docs_v2/06_NFRs/NFRS.md`):
  - E2E latency: **< 30s** typical per post.
  - Caption generation: **< 3s** typical with `4o-mini`.
  - Parallel publish: all platforms done within **10s** typical.

---

### 2. Make Performance Observable (Instrumentation)

**Goal**: Get hard numbers per stage before/after changes.

- Add **timing measurements** around key operations using `log_json` and `correlation_id`:

  - In `WorkflowOrchestrator.execute`:
    - `dropbox_list_images_ms`
    - `image_selection_ms` (downloads + hashing)
    - `vision_analysis_ms`
    - `caption_generation_ms`
    - `sidecar_write_ms`
    - `publish_parallel_ms`
    - `archive_ms`
  - In `WebImageService`:
    - `web_random_image_ms`
    - `web_analyze_ms` (split AI vs sidecar write)
    - `web_publish_ms`

- Use logs to compute **p50/p95 per stage** (simple log queries or scripts) and compare with NFRs.

This is a minimal, low‑risk change and should be done **first**.

---

### 3. Reduce Dropbox I/O and Hashing Cost

#### 3.1 Use Dropbox `content_hash` for deduplication

**Current**:

- In `WorkflowOrchestrator.execute`, dedup is done by:
  - `list_images()`
  - For each image: `download_image()` + local SHA‑256 → check against `posted.json`.
- Complexity: **O(n full downloads)** per run in the worst case.

**Proposed**:

- Extend `DropboxStorage`:

  - Add `list_images_with_hashes(folder) -> list[tuple[str, str]]` that returns `(filename, content_hash)` via `dropbox.files.FileMetadata.content_hash`.

- Refactor image selection in `WorkflowOrchestrator.execute`:

  - Call `list_images_with_hashes` once.
  - Filter out any whose `content_hash` is in `posted.json`.
  - Pick a random unseen image.
  - **Only then** call `download_image` for the chosen image.

- Adjust `utils.state` to store `content_hash` in `posted.json` instead of (or in addition to) local SHA‑256.

**Impact**: For large folders, you go from many full downloads to **one** per run while preserving dedup semantics.

#### 3.2 Avoid redundant downloads in web random‑image path

**Current** (`WebImageService.get_random_image`):

- `list_images` → `get_temporary_link`
- Download sidecar via `download_image`
- Download image again via `download_image` just to compute `sha256` for display.

**Proposed**:

- Prefer a **metadata‑only** hash:

  - Add `get_file_metadata_with_hash` or extend existing metadata method to expose `content_hash`.
  - Use that instead of downloading the full image.

- If SHA is only cosmetic:

  - Consider dropping hash computation from the random‑image response entirely or behind a config flag.

**Impact**: Removes a full image download per random‑image call, improving web UX noticeably under repeated use.

---

### 4. Use Sidecars as a Cache (Avoid Repeat OpenAI Calls)

You already store rich sidecars (`sd_caption + metadata`) per image.

#### 4.1 Reuse sidecars in `/api/images/{filename}/analyze`

**Current**:

- `WebImageService.analyze_and_caption` always calls:
  - `analyzer.analyze(temp_link)` and then
  - `generator.generate`/`generate_with_sd`,
  - then writes/overwrites a sidecar.

**Proposed**:

- Introduce a **config flag**: `web.reuse_sidecar_if_present` (default `true`).

- Behavior for `/api/images/{filename}/analyze`:

  - If a sidecar exists and `reuse_sidecar_if_present` is `true`:
    - Read sidecar via Dropbox (`download_image` or a dedicated text method).
    - Parse with `parse_sidecar_text`.
    - Construct `AnalysisResponse` from sidecar contents (description, mood, tags, nsfw, sd_caption, etc.).
    - **Skip OpenAI entirely**.
  - Add a `force_refresh` query parameter that ignores cache and recomputes analysis/captions via OpenAI, writing a fresh sidecar.

**Impact**: For already processed images, analysis becomes a pure Dropbox read, dramatically reducing latency and cost for the admin UI.

#### 4.2 Align CLI preview and web behavior

- If future CLI preview flows allow browsing existing images, reuse sidecar metadata in the same way for previously processed images.
- Keep behavior consistent between CLI and web to avoid surprises.

---

### 5. Optimize OpenAI Usage and Centralize Rate Limiting

#### 5.1 Centralize AI calls through `AIService`

**Current**:

- `WorkflowOrchestrator` and `WebImageService` often call `analyzer` and `generator` directly.
- `AIService` already defines:
  - `create_caption` and
  - `create_caption_pair` with a shared `AsyncRateLimiter`.

**Proposed**:

- Refactor call sites to use **one canonical path**:

  - For flows that need both caption and `sd_caption`, use `AIService.create_caption_pair`.
  - Where only caption is needed, use `AIService.create_caption`.

- Keep the rate limiter at the `AIService` level and size `rate_per_minute` according to:
  - OpenAI account limits.
  - Expected concurrency (CLI + web workers).

**Impact**: Simpler reasoning about AI throughput, better adherence to rate limits, and more predictable performance.

#### 5.2 Constrain tokens and latency

- In `VisionAnalyzerOpenAI.analyze` and `CaptionGeneratorOpenAI.generate / generate_with_sd`:

  - Set explicit `max_tokens` appropriate to prompts.
  - Keep prompts tight and avoid redundant instructions.
  - Use fast, cost‑effective models (e.g., `gpt-4o-mini`/equivalent) via config defaults, as your NFR suggests.

**Impact**: Reduces p95/p99 latency and API cost with minimal impact on caption/analysis quality.

---

### 6. Web Path Efficiency and Concurrency

#### 6.1 Parallelize independent Dropbox calls

**Current**:

- In `get_random_image`, Dropbox operations are sequential.

**Proposed**:

- Where safe, run them in parallel:

  - Example (conceptual):
    - `get_temporary_link`
    - sidecar download
    - (optional) metadata/hash

  - Use `asyncio.gather` to run these concurrently.

**Impact**: Shaves round‑trip latency for the web UI; more noticeable over higher‑latency links.

#### 6.2 Cache image lists in `WebImageService`

**Current**:

- `list_images` is called on every random‑image request.

**Proposed**:

- Add a simple in‑memory cache in `WebImageService`:

  - `self._images_cache`, `self._images_cache_ts`.
  - Refresh from Dropbox every N seconds (e.g., 30–60) or on cache miss.

**Impact**: For repeated “random” clicks, avoids a Dropbox list call on the hot path.

---

### 7. Ensure Publishers and Image Processing Are Async‑Friendly

#### 7.1 Publishers

- Review `EmailPublisher`, `TelegramPublisher`, `InstagramPublisher`:

  - If they rely on blocking SDKs (e.g., SMTP, Telegram HTTP clients), ensure calls are wrapped in `asyncio.to_thread` or migrate to async clients.
  - Since `WorkflowOrchestrator` uses `asyncio.gather` to publish in parallel, blocking calls would otherwise limit actual concurrency.

#### 7.2 Image resizing

- `utils.images.ensure_max_width` uses Pillow synchronously.

  - If this is invoked from async contexts (e.g., before publish in an async flow), wrap it with `asyncio.to_thread`.

**Impact**: Keeps the FastAPI event loop responsive and makes publisher parallelism effective.

---

### 8. Operational Tuning and Scaling

- **Web server concurrency**:

  - Run multiple Uvicorn workers behind a reverse proxy (e.g., 2–4 workers depending on CPU and external API quotas).
  - Adjust OpenAI rate limits to account for per‑worker concurrency.

- **Timeouts and retries**:

  - You already use `tenacity` for retries with bounded backoff.
  - Ensure underlying Dropbox and OpenAI clients have reasonable timeouts (e.g., 10–20s) to avoid resource exhaustion from hung requests.

---

### 9. Recommended Implementation Order

1. **Instrumentation**: timing in logs for CLI and web stages; establish baseline.
2. **Dropbox optimizations**:
   - `content_hash`‑based deduplication in the workflow.
   - Remove redundant downloads and optionally hash usage in the web random‑image path.
3. **Sidecar‑as‑cache**:
   - Reuse sidecars in web analyze, with `force_refresh`.
4. **Centralized AI service**:
   - Funnel all analyzer/caption usage through `AIService` with a tuned rate limiter and `max_tokens`.
5. **Async hygiene**:
   - Audit publishers and Pillow usage; wrap blocking work in `asyncio.to_thread`.
6. **Web performance polish**:
   - Parallelize independent Dropbox calls and add simple caching for image lists.

This plan keeps your existing architecture and contracts intact while giving you a clear, incremental path to world‑class performance for both the CLI workflow and the FastAPI web interface.

---

### 10. Related Features & Change Requests

- **Feature Requests**  
  - `006_core-workflow-dedup-performance.md` — Core Workflow Dedup Performance (Dropbox `content_hash`-based selection).  
  - `007_cross-cutting-performance-observability.md` — Cross-Cutting Performance & Observability (shared telemetry patterns).  
  - `008_publisher-async-throughput-hygiene.md` — Publisher Async Throughput Hygiene.

- **Change Requests (mapped to existing features)**  
  - `001/001_sidecars-as-ai-cache.md` — Sidecars as AI Cache (Feature 001).  
  - `001/002_sd-caption-ai-service-integration.md` — SD Caption AI Service Integration (Feature 001).  
  - `003/001_analysis-performance-telemetry.md` — Analysis Performance & Telemetry (Feature 003).  
  - `003/002_preview-verbosity-controls.md` — Preview Verbosity Controls (Feature 003).  
  - `005/004_web-performance-sidecar-cache.md` — Web Performance & Sidecar Cache (Feature 005).  
  - `005/005_web-performance-telemetry.md` — Web Performance Telemetry (Feature 005).


