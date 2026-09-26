# PUB-051 — Caption Prompt and Register Repair: Implementation Summary

**Status:** Implementation complete. AC9 (live harness) still pending before merge.
**Date:** 2026-09-26
**Branch:** `feat/pub-051-caption-prompt-and-register-repair`, in worktree `SocialMediaPythonPublisher-pub051`

## Files Changed

**Source (`publisher_v2/src/publisher_v2/`):**
- `utils/captions.py`
  - Removed `STRUCTURE_DIRECTIVES`, `classify_caption_structure`, `pick_structure_directive` and `caption_closing_pattern`.
  - Added `CONTENT_ANGLES` and `pick_content_angle(history, exclude, avoid=)`. `avoid` is a soft preference used to keep angles distinct within one call.
  - Added `strip_emoji_and_hashtags`.
  - `build_caption_sidecar` now flattens `sd_caption` onto one line.
- `services/ai.py`
  - Caption call sampling: temperature 0.9, frequency penalty 0.3, presence penalty 0.6.
  - The analysis is rendered as prose, capped at 260 chars, with no tags, palette or aesthetic terms.
  - The prompt carries at most two openings, no closing line and one `Angle:` line.
  - Smart-hashtag platforms get a `Topics:` line built by `hashtag_topics`.
  - The multi-caption call requests platform keys only.
  - `create_multi_caption_pair_from_analysis(..., history_angles=)` returns `(captions, None, usages, angles)`.
  - Angles are distinct per call. On regeneration the rejected angle is a hard exclusion and the other platforms' angles are a soft one.
  - Vision uses one call with two registers: `OWNER_PERSONA_MARKER`, `SENSES_POOL`, `senses_seed` (off the event loop), and `owner_persona_text`/`tenant_persona` (the tenant persona is capped at 600 chars and sanitized). `sd_caption` is parsed from the vision reply.
  - Vision gets one retry on a JSON parse failure, and logs `vision_sd_caption_missing` when the reply lacks it.
  - `_sanitize_analysis_field` now redacts every occurrence of each marker.
  - Removed: `_DEFAULT_VISION_*`, `generate_multi_with_sd`, `sd_suffix` and `sd_caption_brief`.
- `config/static/ai_prompts.yaml`
  - New `vision.sd_caption` key, requested only when `sd_caption_enabled`.
  - The persona is written as a person.
  - `caption.rules` has a "write X instead of Y" line for each of the 18 tells.
  - Each platform style is a speaker→audience stance.
- `config/static_loader.py`: adds the `AIVisionPrompts.sd_caption` field. A custom static dir that lacks the key falls back to the packaged text; an explicit `null` opts out.
- `db/models.py`, `alembic/versions/004_add_caption_angle_column.py`: nullable `angle String(64)`, added as an additive migration.
- `db/caption_store.py`: `save_captions_batch(angles_by_platform=)` and a new `fetch_recent_with_angles_by_platform`.
- `services/sidecar.py`, `services/sidecar_parser.py`
  - New `caption_angles` metadata, validated to pool keys when read.
  - `update_sidecar_with_caption` now returns `SidecarCaptionUpdate(duration_ms, prior_view)`.
- `core/workflow.py`
  - Stored angles are fed into rotation.
  - History is saved only for platforms that published successfully, with their angle. Reused captions and unedited override captions take the angle from the sidecar view that was already read, so there is no extra download.
  - AC7: a retry reuses the captions through `_reuse_generated_captions`.
  - `sd_caption` is taken from vision, and `sd_caption_from_vision` is logged. The stale `sd_caption_start`/`complete` events were removed.
  - `_select_image` shuffles a copy of the list.
- `web/service.py`: unpacks the 4-tuple, reads the stored angles, falls back to vision for `sd_caption`, and writes `caption_angles` to the sidecar.
- `app.py`: the preview sidecar's `model_version` names the vision model when the SD prompt came from vision.
- `scripts/caption_eval.py` and `scripts/caption_sample.py`: tolerant unpack of the 4-tuple.

**Docs:**
- `docs_v2/07_AI/AI_PROMPTS_AND_MODELS.md`
- `docs_v2/02_Specifications/SPECIFICATION.md`
- `docs_v2/roadmap/README.md` (status In Progress)
- the spec status
- handoff notes
- `CHANGELOG.md`

**Tests:**
- New files: `test_caption_angle_rotation.py` and `caption_pipeline_fakes.py` (shared fakes).
- Extended: prompt payload, multi-caption, vision telemetry, error paths, caption history DB, context intelligence, sidecar builders and parser, analysis context, app CLI, and the web service coverage tests.

## Acceptance Criteria

- [x] **AC1:** `test_each_platform_receives_exactly_one_angle_per_call`, `test_angle_rotates_across_three_renders_using_stored_column`, `test_regeneration_picks_a_different_angle_than_the_rejected_draft`
- [x] **AC2:** `test_no_closing_pattern_line_is_ever_rendered`, `test_at_most_two_openings_to_avoid_appear_per_platform`
- [x] **AC3:** `test_user_message_under_500_tokens_with_history_and_six_examples` (471 by len/4), `test_analysis_prose_contains_no_hex_colour_or_snake_case_tag`. Met on the spec's fixture only; see Open questions.
- [x] **AC4:** `test_caption_call_requests_platform_keys_only_no_sd_caption`, `test_caption_call_sampling_params_match_configured_values`
- [x] **AC5:** `test_sd_caption_comes_from_the_neutral_register_vision_call`, `test_caption_facing_fields_carry_the_owner_persona_marker`
- [x] **AC6:** `test_senses_pool_prompt_text_differs_by_image_seed`, `test_caption_facing_fields_stay_out_of_sidecar_after_vision_restructure`
- [x] **AC7:** `test_partial_retry_makes_zero_additional_ai_calls`, `test_caption_history_holds_one_row_per_successfully_published_platform_only`
- [x] **AC8:** `test_non_json_vision_reply_retried_once_at_same_resolution_before_fallback`
- [ ] **AC9:** not run. It needs `OPENAI_API_KEY`, which isn't available in this environment. Run `PYTHONPATH=publisher_v2/src uv run python scripts/caption_eval.py --nightly --out build/caption-eval` and paste the table into the PR.

All 16 test names from the handoff exist exactly as named.

## Quality Gates

Final numbers are from the last full run; see the verdicts below.
- Format: ✅
- Lint: ✅
- Type check: ✅ (65 files)
- Tests: 1862 passed, 1 skipped, 0 failed, in random order.
- Coverage: 93% overall.

| Module | Coverage |
|---|---|
| `services/ai.py` | 95% |
| `core/workflow.py` | 95% |
| `utils/captions.py` | 99% |
| `db/caption_store.py` | 97% |
| `services/sidecar.py` | 97% |
| `services/sidecar_parser.py` | 94% |
| `config/static_loader.py` | 97% |
| `app.py` | 88% |
| `web/service.py` | 83% |

## Subagent Verdicts

- `code-reviewer`: four passes, all PASS WITH NITS. Every warning was fixed. The final delta pass left only nits:
  - the app.py preview heuristic, recorded under decisions below;
  - an extra content-free `sidecar_metadata_json_invalid` log on a malformed sidecar;
  - one docstring line over 120 characters;
  - a partial custom static dir now inherits the packaged `vision.sd_caption`, which is intended.
- `security-auditor`: four passes, all PASS. Fixed along the way:
  - sidecar line injection;
  - first-occurrence-only marker redaction;
  - line breaks joining words and letting markers slip past redaction;
  - SHA-256 hashing on the event loop.

  Noted and not fixed: Unicode look-alike characters get past the marker blocklist. That is a limit of any blocklist, and the blocklist is only a second line of defence.

## Decisions and deviations for the owner to acknowledge

- **Angle pool:**
  - `sensation` — Dwell on one physical sensation.
  - `moment` — Dwell on the moment before or after the shot.
  - `detail` — Dwell on one small detail most would miss.
  - `craft` — Dwell on how it was made: one choice you made.
  - `atmosphere` — Dwell on the room: its air, sound and light.
  - `direct_address` — Speak to the reader directly, as if handing them the photo.
- **Distinct angles within one call:** a deviation from AC1's literal "ties by pool order".
  - Without it, every platform got the same angle on every run. The Lead's critique confirmed this by running the code.
  - A platform can now take its second-oldest angle.
  - Per-platform rotation still holds with up to 5 platforms.
- **`excluded_directives`:** always empty. It stays as a hook, because no angle contradicts a brief.
- **Vision design:** one call with two registers instead of two calls. The spec allows either.
  - Cost: about +110 input and +60 output tokens on gpt-4o, roughly $0.001 per image.
  - The existing call-count tests pin one call per resolution.
- **Vision temperature:** stays at 0.4. With one call, a single temperature also governs nsfw, labels and alt_text.
  - Variety in the owner fields comes from the seeded senses pool instead.
  - In the same call, the tenant persona can influence the neutral fields. It carries the same authority as the tenant's caption persona, and nothing gates on those fields.
- **SD prompt:** now written by gpt-4o instead of gpt-4o-mini.
  - `generate_multi_with_sd` and `sd_caption_brief` are deleted.
  - Kept for the single-platform fallback: `generate_with_sd`, the `sd_caption_*` override resolution and the YAML `sd_caption:` block.
- **Config semantics change (orchestrator-owned fields; filed as dhirmadi/platform-orchestrator#222):**
  - On the multi-platform path, `sd_caption_single_call_enabled`, `sd_caption_model`, `sd_caption_system_prompt` and `sd_caption_role_prompt` no longer have any effect.
  - Multi-platform captions now use `model`. A tenant that had set `sd_caption_model` had its captions written by that model; they are now written by `model`.
  - The wire contract is unchanged, but the orchestrator repo should document it.
- **Sampling regimes kept:**
  - An all-email call stays at 0.5 (PUB-046).
  - The single-platform `generate()` stays at 0.7 (`SINGLE_PLATFORM_CAPTION_TEMPERATURE`).
- **Web publishes and the sidecar:**
  - A web publish with unedited overrides records the generated angle; an edited override stores NULL.
  - No extra storage read: the angle comes from the sidecar view that `update_sidecar_with_caption` already parsed.
- **Partial-retry trust:** a retry publishes the sidecar's `caption_generated` without regenerating it. The sidecar lives in tenant-controlled storage and is written only by this app. Accepted as a trust boundary.
- **JSON retry:** it stacks with `@_ai_retry` and the fallback. In the worst case a chain makes 6 vision calls, 12 in pathological cases, where it made 3 and 6 before. The normal path is still one call.
- **`update_sidecar_with_caption`:** returns a NamedTuple instead of a float. The only production caller is the workflow.
- **`app.py` preview `model_version`:** uses a heuristic (sd enabled plus a multi-capable service). It is wrong only for a generator without multi support that also returns an empty SD prompt.
- **Delivered as one PR closing #191, #192 and #194**, not three. #191 cannot ship alone (the sd_caption sequencing constraint), and the pre-commit hook blocks commits whose tests are red, so the changes cannot be split into green commits.
- **Approved scope growth:**
  - User-approved on 2026-09-25: `web/service.py` and the `scripts/` changes.
  - From the critique round, which the user asked to "address all findings": `services/sidecar.py`, `sidecar_parser.py`, `static_loader.py`, `app.py`, and the plan's allow-list.
  - `_select_image` shuffles a copy of the list; the in-place shuffle was making a new test flaky.

## Tests changed or removed because the spec changed

- `TestStructureDirectiveRotation` was removed; the angle tests replace it.
- Closing-line asserts were inverted.
- The directive tests became angle tests. `test_regeneration_angle_respects_platform_exclusions` became `test_single_platform_regeneration_prompt_carries_the_one_returned_angle`, because its exclusion assert could never fail.
- Tests of `generate_multi_with_sd` were removed, along with `test_sd_still_requested_in_user_prompt` and the multi-path SD-fallback logging test.
- Temperature 0.7 was changed to 0.9 plus the penalties. This includes the renamed `test_ai_email_length_control.py` tests `..._uses_default_caption_temperature`.
- `test_alt_text` now reads the YAML instead of `_DEFAULT_VISION_*`.
- The web fake now routes on the call shape instead of the `"sd_caption"` substring.
- The 4-tuple stubs fail loudly, instead of falling through to real OpenAI.

## Harness (PUB-049) changes

- `scripts/caption_eval.py --nightly` now threads `history_angles` across the 20 fixtures in order, as production does across successive publishes, capped at `caption_history.window_size`.
- Snapshot entries now record `angles`.
- `report.md` gains an `## Angle distribution` table, so the spec's "roughly uniform over 20 images" can be read directly.
- Tests:
  - `test_nightly_threads_angles_across_fixtures_like_sequential_publishes`
  - `test_nightly_snapshot_records_angles_per_entry`
  - `test_nightly_report_includes_angle_distribution`

## Open questions and follow-ups

- **AC3 spec gap: resolved.** The spec was clarified on 2026-09-26. The 500-token bound applies to the test fixture only.
  - The under-500-tokens claim holds only on the spec's fixture of ~60-char voice examples.
  - `DEFAULT_VOICE_PROFILE_TOKEN_BUDGET` (500) lets the examples alone exceed 500.
  - A heavy fixture (120-char examples plus seed hashtags) measures about 570, and realistic 200-char email examples would reach about 690.
  - `test_heavy_tenant_user_message_stays_under_600_tokens` guards against further growth. The spec and PUB-029's budget contradict each other.
- **Tells priming:** the 18 "instead of Y" lines quote each tell verbatim, as the spec requires. AC9 will show whether quoting them primes the model to use them.
- **Vision rate limiter: resolved.** Added on the owner's instruction (2026-09-26). Every vision create call, including the JSON retry and the fallback pass, now acquires the shared `AIService` limiter (`test_vision_calls_acquire_the_shared_rate_limiter`). At a very low `ai_rate_per_minute`, limiter waits count toward the #84 AI-stage deadline.
- **Merge with PUB-050:** its work in progress touches `services/ai.py`, `core/workflow.py` and `web/service.py`, and its voice sampling feeds the AC3 size.
- **Out of scope:** `scripts/vision_token_benchmark.py` sends `vision.user` only, so it no longer asks for `sd_caption`.
