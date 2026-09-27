# PUB-084: DRY Review Standalone Batch

| Field | Value |
|-------|-------|
| **ID** | PUB-084 |
| **Category** | Foundation |
| **Priority** | P2 |
| **Effort** | L |
| **Status** | In Progress |
| **Dependencies** | — (waves 1-2 are prerequisites for PUB-054, PUB-056 step 1 and PUB-058) |

## User Story

As the maintainer, I want the review findings that no roadmap item owns fixed in one tracked batch, so that the test suite stops fighting the refactors queued behind it and the two latent bugs are gone.

## Problem

The 2026-09-27 DRY/over-engineering review ([#291](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/291)) filed 26 issues. Fifteen were folded into existing roadmap items. The eleven below have no owning spec:

- **Bugs:** #296 (eight test files run the workflow against the real `~/.cache` posted-state), #272 (logout handler re-registered on every `disableButtons()` call), #273 (Instagram tenant always `"default"`).
- **Test suite:** #297 (hand-rolled OpenAI fakes, `AIService` subclasses, config builders, 19 dead fixtures), #298 (copied web harnesses, stale route-auth inventory, auth patched out), #299 (~140 tests pin `index.html` source text), #300 (redundant tests).
- **Code:** #294 (dead scripts and shims), #286 (meter plumbing), #281 (caption utility leftovers), #277 (`index.html` JS duplication).

Several are prerequisites of roadmap items: #296 before PUB-054/PUB-058 rename the posted-state helpers (48 inline patches would break), #297's config helper before PUB-056 step 1 (92 test files), #299 before #277, and #281 before PUB-052 touches the same caption code.

## Owner decisions (2026-09-27)

- **#273:** Instagram is not in use. Drop the unused `tenant` option and document the single-instance limit; do not plumb a tenant id.
- **#281:** A caption must never exceed its platform limit. The hard limit wins over keeping trailing hashtags. This also covers the FetLife subject prefix: `"Private: "`/`"Avatar: "` counts toward the 240-character subject limit measured in #146.
- **#294:** `scripts/heroku_hetzner_clone.py` is not used. Delete it.
- **#299:** Implementer's choice, delegated by the owner — see Scope wave 3. The owner's delegation approves adding `pytest-playwright` as a dev dependency for this purpose.
- **Delivery:** one PR per wave, from one worktree branch.
- **PUB-053 ordering:** #201 (dedicated storage executor) runs last inside PUB-053, after PUB-056 has landed #274's single `ManagedStorage` call helper.

## Desired Outcome

The eleven issues are closed. The suite no longer touches the developer's home directory, each fake and builder exists once, `index.html` can be refactored without editing tests, browser behaviour is covered by a few real browser flows, and no caption or email subject can exceed its platform limit.

## Scope

**In scope (five waves, one PR each, in order):**

1. **Isolation and Instagram (#296, #273)**
   - Autouse `_isolate_env` sets `XDG_CACHE_HOME` to a per-test temp dir; delete the seven `_isolated_posted_state` copies, `bypass_dedup`, and inline posted-hash patches that exist only for isolation.
   - `InstagramPublisher` loses its `tenant` parameter (the `session_store` seam stays; tests use it); the session key is a module constant; module docstrings and `docs_v2/05_Configuration/CONFIGURATION.md` state that Instagram supports one instance per database.
2. **Test infrastructure (#297, #298)** — test-only, no production change
   - `caption_pipeline_fakes.FakeOpenAI` gains a scripted-response mode (payloads or exceptions, replayed in order) and a `fake_openai` fixture; the eleven hand-rolled OpenAI chains go.
   - Tests build `AIService(analyzer, generator)` with shared fakes; no test subclasses `AIService`. One home for shared fakes.
   - The 19 unused conftest fixtures are deleted; one `make_app_config(**overrides)` helper replaces the per-file builders.
   - `tests/web/conftest.py` holds one real-app harness (`real_app_env`), one per-key `FakeS3` with `managed_real_app`, one `analyze_service` builder, and the hoisted library fixtures (with `FEATURE_LIBRARY` unset inside).
   - One route-auth inventory without source line numbers, parametrised over the auth matrix and covering every admin route including library routes. No test replaces `require_auth`/`require_admin` with a no-op.
3. **Browser tests and pruning (#299, #272, #300)**
   - Replace the ~140 `index.html` source-grep tests with (a) one parametrised element-contract test (ids and `data-*` hooks the UI relies on), fetching the page once, and (b) a small `pytest-playwright` suite, marker `e2e`, deselected from the default run and executed in its own CI job, covering: upload queue locks controls while uploading; bulk delete retries failed items; keep/remove/delete each send one request; logout sends exactly one request after repeated actions (#272).
   - Fix #272: register the logout handler once and drop its redundant header.
   - #300: merge the upload test files, replace the Markdown fence parser in `test_requirements_files.py` with a regex, parametrise identical test bodies, delete tests of test doubles and existence-only tests, fold the keep/remove config tests into `config/`.
4. **Dead code (#294, #286)**
   - Delete `scripts/heroku_hetzner_clone.py`, `scripts/servers.txt`, their test and the two doc references; delete `scripts/{migrate,cleanup,refine}_features.py` and `rename_artifacts.py`; delete `tools/__main__.py`; repoint the three tests using `web/sidecar_parser.py` and delete the shim. Update PUB-060's two now-obsolete bullets.
   - Meters: one shared `_spawn_if_loop`; delete `stop_periodic_flush`, `pending_batch_count`, the `_drain_loop` catch-all; `_pending_max` becomes a module constant; `UsageMeter.emit_all` delegates to `emit`.
5. **Caption limits and JS dedup (#281, #277)**
   - `format_caption` truncates with `smart_truncate` and one limit lookup; output never exceeds the limit. `_trim_to_length` is deleted.
   - Email subject: prefix plus caption never exceeds the email limit (the caption is truncated to `limit - len(prefix)` when it goes in the subject).
   - Shared hashtag/emoji regexes; history narrowed to `dict[str, list[str]] | None` with the test-only history helpers deleted; `_create_vision_completion`'s `TypeError` retry removed (test doubles fixed); one logger and one seed helper in `services/ai.py`; `build_metadata_phase2` as a field-map loop with byte-identical output.
   - `index.html`: one `postImageAction` helper for the five admin actions, one library-delete helper, one `DEFAULT_FEATURES`, one image-list loader, dead `#env-indicator` and `data.images` fallback removed.

**Out of scope:**
- Anything folded into PUB-052/053/054/056/057/058/059/064/078 (see #291).
- The overshoot condense block and `format_caption`'s ladder location in `_MAX_LEN` (PUB-052 AC10, PUB-057 step 2) — this item unifies the truncation algorithm only.
- Plumbing a tenant id into Instagram.
- Template redesign.

## Acceptance Criteria

- AC1: Given the autouse test setup, when any test runs, then `XDG_CACHE_HOME` points inside that test's temp dir and `utils.state` resolves its cache path there, never under the real home directory
- AC2: Given `publisher_v2/tests`, when it is searched, then no per-file `XDG_CACHE_HOME` fixture and no `bypass_dedup` fixture exist
- AC3: Given `InstagramPublisher`, when its constructor signature is inspected, then it has no `tenant` parameter, and every session-store call uses one module-level key
- AC4: Given `FakeOpenAI` with a script of payloads and an exception, when the client is called repeatedly, then it replays them in order, and no test file outside `caption_pipeline_fakes.py` defines an OpenAI response chain or patches `AsyncOpenAI` by hand
- AC5: Given `publisher_v2/tests`, when it is parsed, then no class subclasses `AIService`
- AC6: Given every fixture defined in a `conftest.py`, when test files are scanned, then each has at least one user
- AC7: Given `make_app_config(**overrides)`, when called with overrides, then they are applied on top of valid defaults, and direct `ApplicationConfig(` construction in tests is limited to the helper and to tests of the model itself
- AC8: Given `tests/web`, when it is parsed, then each of the S3, Dropbox, OpenAI, Telegram-bot and SMTP fakes is defined once, and the S3 fake's `head_object` answers per key
- AC9: Given the running app's admin routes, when the route-auth inventory is compared with them, then every admin route (including library routes) is in the inventory, the inventory holds no source line numbers, and no test replaces `require_auth` or `require_admin` with a no-op
- AC10: Given `publisher_v2/tests`, when it is searched, then no test regex-matches a JavaScript function body in `index.html`, and one parametrised test asserts the required element ids and `data-*` hooks from a single page fetch
- AC11: Given the `e2e` suite in a headless browser, when the four flows run (upload lock, bulk-delete retry, one request per keep/remove/delete, one logout request after repeated actions), then each passes; given the default `uv run pytest`, then `e2e` tests are deselected and no browser is required
- AC12: Given `publisher_v2/tests`, when test bodies are compared with constants stripped, then no two test functions are identical unless listed in an explicit allowlist with a reason, and `test_requirements_files.py` contains no Markdown parser
- AC13: Given the repository, when its tracked files are listed, then the clone script, `servers.txt`, the four docs-migration scripts, `tools/__main__.py` and `web/sidecar_parser.py` are absent and nothing references them
- AC14: Given no running event loop, when a meter schedules a background task, then it is a no-op through the one shared helper; given `aclose`, then pending batches are still flushed
- AC15: Given any caption and platform, when `format_caption` runs, then the result is at most the platform limit and cut at a sentence or word boundary by `smart_truncate`
- AC16: Given `subject_mode` private or avatar and a caption at the email limit, when `EmailPublisher` builds the subject, then prefix plus caption is at most the email limit
- AC17: Given the phase-2 metadata fixtures, when `build_metadata_phase2` runs, then its output is byte-identical to before the refactor
- AC18: Given `_create_vision_completion`, when the client raises `TypeError`, then the error propagates and no second request is made
- AC19: Given `index.html` after the JS dedup, when the element-contract test and the `e2e` flows run, then they pass without their expectations being edited
- AC20: Given this item ships, when its implementing PRs merge, then #272, #273, #277, #281, #286, #294, #296, #297, #298, #299 and #300 are closed with `Closes #N` in the PR body of the wave that resolves each

## Implementation Notes

- Waves 2-4 change no production behaviour; the suite's pass/fail set must be unchanged apart from deleted tests, and coverage must stay at or above 85%.
- Wave order matters: wave 1 before PUB-054/PUB-058 (posted-state helper rename); wave 2's `make_app_config` before PUB-056 step 1; wave 3 before wave 5's JS dedup; wave 5 before PUB-052.
- The `e2e` suite runs the real FastAPI app under uvicorn with the managed-storage fakes from wave 2 and an admin cookie minted by the test (no Auth0 network call).

## Risks

- Deleting duplicate tests can drop coverage of a real branch; mitigated by comparing coverage per module before and after each pruning commit.
- Browser tests can be flaky; mitigated by keeping them to four flows, waiting on network/DOM events rather than timeouts, and running them in their own job.

## Related

- Tracker [#291](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/291); owner decisions recorded on 2026-09-27
- [PUB-060](PUB-060_test-and-docs-hygiene.md) — wave 4 obsoletes two of its bullets (clone-script assertion, `normalize_name`)
- [PUB-053](PUB-053_shared-dyno-isolation.md) — #201 sequencing decision above
- [#146](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/146) — FetLife 240 measurement behind AC16

## Change Log

- 2026-09-27 — Created from the #291 review's standalone issues with the owner's decisions; hardened directly into Not Started with a handoff because the owner approved the plan and its decisions in the same session.
