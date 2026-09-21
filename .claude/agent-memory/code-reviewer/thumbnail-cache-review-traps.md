---
name: thumbnail-cache-review-traps
description: Traps when reviewing ManagedStorage thumbnail-cache / invalidation changes (#86, #140) — invalidation must live in ManagedStorage, plus the generation-counter store-after-write guard
metadata:
  type: project
---

`ManagedStorage._thumb_cache` (`services/managed_storage.py`) is **per-instance**, TTL 900s default
(`WEB_THUMBNAIL_CACHE_TTL_SECONDS`). Since #140 it is keyed by `(endpoint, bucket, key, size)` and
only revalidates the ETag once the TTL lapses, so correctness depends entirely on explicit
invalidation from every write path.

**Why:** #86 keyed the cache by ETag, which made staleness structurally impossible but billed one
`head_object` per cache hit. #140 traded that for explicit invalidation.

**How to apply — when reviewing any thumbnail/caching change:**
- `WebImageService.storage` is ONE `ManagedStorage` instance shared by the library router, the
  thumbnail endpoint, AND `WorkflowOrchestrator`. A hook added only in `web/routers/library.py`
  misses `keep_image` / `remove_image` / `delete_image` / publish→`archive_image`. As of #140 the
  correct shape is in-class: `put_object`, `delete_object`, `move_object`, `archive_image`,
  `move_image_with_sidecars`, `delete_file_with_sidecar` each call `self.invalidate_thumbnail(...)`
  after their `to_thread` succeeds. Any NEW write method added to `ManagedStorage` must do the same
  — nothing enforces it.
- Store-after-write race: `_thumb_generation[key]` is bumped by `invalidate_thumbnail`;
  `_regenerate_thumbnail` snapshots it before `download_image` and refuses `_store_thumb` if it
  moved. Without that guard an in-flight download re-populates the cache right after the eviction.
  The dict is never pruned (grows with every distinct written key, sidecars included) and is not
  cleared by `aclose()` — bounded by object count, safe direction, but worth a nit.
- Cache is per-process: `heroku ps:scale web=2` or `uvicorn --workers N` silently reintroduces
  staleness, as does any out-of-band write (migrate_storage tool, R2 console). Procfile runs one
  bare uvicorn today. Documented in `docs_v2/05_Configuration/CONFIGURATION.md`.
- `format` has never been part of the thumbnail cache key (pre-existing since #86).
- `WebImageService.analyze_and_caption` calls `ensure_known_image` before `_analyze_and_caption_impl`
  (the only caller), so the analyze 404 comes from there, not from `get_temporary_link`. But
  `ensure_known_image` consults the **cached** listing — with Dropbox as backend, a deleted-but-
  still-listed image now surfaces as a download StorageError (500) instead of a temp-link 404.
- For ManagedStorage, `get_temporary_link` is `generate_presigned_url` — local signing, NOT a
  billed op and it never 404s. Only Dropbox's version is a real API call.
- Op-count tests: prefer patching `boto3` at construction and counting client calls over mocking
  `get_file_metadata`/`download_image`; the latter hides the real billed ops. See also
  [[storage-protocol-review-traps]].

**Round 2 (#140 PR #159, single-flight + finally-invalidation):**
- `_last_get_etags` (key → ETag recorded by `download_image`'s GET) is written by **every**
  download in the process (workflow publish, analyze, migrate_storage), but popped only by
  `_regenerate_thumbnail` and only when the HEAD failed (`etag = etag or pop(...)` short-circuits).
  Unbounded, cleared only in `aclose()`. Same defect class as the `_thumb_generation` growth that
  was fixed one commit earlier.
- The production half of that ETag recording (`managed_storage.py` `_download`:
  `self._last_get_etags[key] = ...`) survives deletion: the test fakes `download_image` and writes
  the dict itself. Always mutation-test both halves of a producer/consumer pair.
- `_thumb_lock` prune loop and the `existing[0] is not loop` branch are uncovered and survive
  mutation; evicting an in-use lock silently drops mutual exclusion (duplicate work, not
  corruption).
- `test_two_different_keys_do_not_serialise_on_each_other` (peak in-flight == 2) kills a *global*
  lock but NOT "no lock at all" — it proves non-serialisation, not per-key locking.
- `_THUMB_GENERATION_MAX_KEYS` (4096) is reused as the lock-map bound; name lies.
