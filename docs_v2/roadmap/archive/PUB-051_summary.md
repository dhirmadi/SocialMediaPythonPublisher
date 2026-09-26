# PUB-051 — Caption Prompt and Register Repair: Implementation Summary

**Status:** Done (merged via PR #228)
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
- [~] **AC9 (verification, human-run): met for opener share and tells rate; TF-IDF "does not rise" not demonstrated (see deviations).** the harness `--nightly` ran live on 2026-09-26, 5 runs on this branch against 5 runs on current `main` (same fixtures and model). The committed `snapshot.json` is a synthetic bootstrap (hand-shaped captions, PUB-049), so it is not a real baseline; `main`'s own live output is. Means (main → PUB-051):

  | Metric | main | PUB-051 | |
  |---|---|---|---|
  | opener/closer 3-gram share | 0.303 | **0.213** | mean −30%; per-run max 0.300 vs main's 0.433 (the success metric asks for a max under 30%: at the bar, not under) |
  | tells-lexicon hit rate | 0.077 | **0.040** | about halved |
  | two-sentence+emoji rhythm | 0.023 | 0.003 | |
  | vision-field overlap | 0.256 | 0.135 | |
  | distinct-1 / distinct-2 | 0.299 / 0.742 | 0.327 / 0.795 | |
  | TF-IDF bigram cosine to history | 0.0052 | 0.0058 | +11%, within run noise (ranges 0.0042–0.0060 vs 0.0051–0.0063, t≈1.4) |

  Angle distribution over 20 images, per platform: every angle 3–4 times (uniform). The small TF-IDF rise comes from concrete nouns ("the light", "the floor", "the rope") shared with the synthetic history, which describes the same objects; concrete in-frame detail is the owner's stated style (#179). Getting there took three prompt iterations measured live: the first live run had opener share 0.40 because email replies carried a `Subject:` header and angle/stance wording was echoed as openers ("After the session…", "I chose to…", "Just out of…", "Look closely…").

All 16 test names from the handoff exist exactly as named.

## Quality Gates

Final numbers are from the last full run; see the verdicts below.
- Format: ✅
- Lint: ✅
- Type check: ✅ (65 files)
- Tests: 1924 passed, 1 skipped, 0 failed, in random order (two runs).
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

- `code-reviewer`: the Lead's own critical PR review found the angle-starvation bug and the SD-prompt coupling. A full pre-merge review was BLOCKED on merge drift from main (8 PUB-050 tests); that is resolved by the merge and the adapted tests, and a final pass on the merged tree follows. Earlier: four passes, all PASS WITH NITS. Every warning was fixed. The final delta pass left only nits:
  - the app.py preview heuristic, recorded under decisions below;
  - an extra content-free `sidecar_metadata_json_invalid` log on a malformed sidecar;
  - one docstring line over 120 characters;
  - a partial custom static dir now inherits the packaged `vision.sd_caption`, which is intended.
- `security-auditor`: the pre-merge audit passed and found two sidecar data-integrity issues, both fixed with tests: a run without an SD prompt would blank an existing one, and an override publish would move the social caption into line 1. Earlier: four passes, all PASS. Fixed along the way:
  - sidecar line injection;
  - first-occurrence-only marker redaction;
  - line breaks joining words and letting markers slip past redaction;
  - SHA-256 hashing on the event loop.

  Noted and not fixed: Unicode look-alike characters get past the marker blocklist. That is a limit of any blocklist, and the blocklist is only a second line of defence.

## Decisions and deviations for the owner to acknowledge

- **Angle pool:**
  - `sensation` — Topic: one physical sensation.
  - `moment` — Topic: what the camera did not see.
  - `detail` — Topic: one overlooked detail.
  - `craft` — Topic: a decision behind the picture.
  - `atmosphere` — Topic: the sound and temperature of the space.
  - `direct_address` — Topic: the reader, spoken to directly.
  - Written as topic noun phrases with no verbs: the earlier "Dwell on …" texts were echoed as caption openers in live runs.
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
- **Angle history depth (fixed after the Lead's PR review):** a three-deep `window_size` against a six-angle pool cycled through only four angles, and `atmosphere`/`direct_address` were never used. Stored angles are now read `angle_history_depth(window_size) = max(window_size, len(CONTENT_ANGLES))` deep in the workflow, web Analyze and the harness. Caption-text history stays at `window_size`; web Analyze now also uses `window_size` for text (previously 8), so its similarity gate compares against 3 captions.
- **Sidecar without an SD prompt:** the sidecar is written whenever captions were generated, so retry reuse (AC7), the web cache and angle recording also work with `sd_caption_enabled=False` or when vision omits the SD prompt. Line 1 is empty in that case, or keeps an earlier SD prompt (never blanked). `sd_caption_version` is omitted when there is no SD prompt. An override publish never moves the social caption into line 1 (the old fallback was removed). With SD prompts on, web Analyze treats an empty cached SD line as a cache miss and regenerates, but only when the sidecar holds no operator caption (`caption_submitted`, or `caption` with `caption_edited`); otherwise it is a cache hit as on main, so the operator's edits are never overwritten (`test_web_analyze_keeps_operator_captions_when_cached_sd_line_is_empty`). Consequence: tenants with SD prompts off now get a `.txt` sidecar per processed image.
- **Opener hygiene (from live AC9 runs):** the multi-caption prompt carries "An angle is the subject, not its first words." and "Each caption opens differently."; email replies have any `Subject:` label stripped and are joined to one line; em dashes are removed from every caption; stances carry no scene or time phrase.
- **CRAFT rules, informed by the owner's style guide (#179), kept tenant-neutral:** open with a concrete noun or short plain statement (never I chose / The way / Notice / Look / Here's / Just); anchor a concrete detail and one thing that happened in the room; no em dashes; no similes; vary the ending (statement, direct question, short instruction); never invite the reader into the scene. The rope-specific voice (dominance, consent, care) is documented as a tenant `system_prompt` example; the owner's 20 example captions belong in `content.voice_profile` (platform-orchestrator#223).
- **Follow-up (PUB-049 harness, not this item):** the committed `snapshot.json`/thresholds are a synthetic bootstrap. Live output from both `main` and this branch misses several min-direction bars (distinct-1 ≈0.3 vs 0.445), so a live nightly regeneration would fail its offline scoring until the bars are re-derived from a real snapshot (`--generate-thresholds`, a deliberate human step). The nightly workflow also has no `OPENAI_API_KEY` repo secret.
- **AC9 deviations for the owner to acknowledge:** (1) the baseline is `main`'s own live output over 5 runs, not the committed PUB-049 snapshot, which is a synthetic bootstrap and not model output; (2) TF-IDF cosine to history rose 0.0052 → 0.0058 (+11%). The run ranges overlap and the difference is not significant at n=5 (t≈1.4), but "does not rise" is not demonstrated. The rise tracks concrete nouns shared with the synthetic history.
- **Tested vs prompt copy:** the CRAFT rules and the Light-last prose order are prompt wording and are not pinned by tests (the spec asks tests to assert structure); their effect is measured only by the live harness.
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

## Tests added in the pre-merge round

- `test_production_window_rotation_uses_every_angle_over_twenty_runs`
- `test_web_analyze_reads_angle_history_as_deep_as_the_pool`
- `test_nightly_angle_window_is_at_least_the_pool_size`
- `test_partial_retry_reuses_captions_when_sd_caption_disabled`
- `test_web_analyze_writes_sidecar_without_sd_prompt`
- `test_sidecar_without_sd_prompt_round_trips_metadata`
- `test_sidecar_without_sd_prompt_is_never_written_in_preview_dry_or_debug`
- `test_sidecar_write_without_new_sd_prompt_keeps_the_existing_one`
- `test_override_publish_never_moves_the_social_caption_into_the_sd_slot`
- `test_web_cache_regenerates_when_sd_enabled_and_cached_sd_line_empty`
- `test_ac3_holds_with_pub050_sampled_voice_examples`
- Changed: `TestUpdateSidecarWithCaption::test_creates_minimal_sidecar_when_none_exists` now expects an empty line 1, not the social caption.

## Open questions and follow-ups

- **AC3 spec gap: resolved.** The spec was clarified on 2026-09-26. The 500-token bound applies to the test fixture only.
  - The under-500-tokens claim holds only on the spec's fixture of ~60-char voice examples.
  - `DEFAULT_VOICE_PROFILE_TOKEN_BUDGET` (500) lets the examples alone exceed 500.
  - A heavy fixture (120-char examples plus seed hashtags) measures about 570, and realistic 200-char email examples would reach about 690.
  - `test_heavy_tenant_user_message_stays_under_600_tokens` guards against further growth. The spec and PUB-029's budget contradict each other.
- **Tells priming:** the 18 "instead of Y" lines quote each tell verbatim, as the spec requires. AC9 will show whether quoting them primes the model to use them.
- **Vision rate limiter: resolved.** Added on the owner's instruction (2026-09-26). Every vision create call, including the JSON retry and the fallback pass, now acquires the shared `AIService` limiter (`test_vision_calls_acquire_the_shared_rate_limiter`). At a very low `ai_rate_per_minute`, limiter waits count toward the #84 AI-stage deadline.
- **Merge with PUB-050: done.** `origin/main` (with PUB-050 #226, #227, #229, #230) was merged into the branch. The 8 PUB-050 tests that assumed the old 3-tuple and old caption-call shape were adapted to the shared fakes; their voice-sampling assertions are unchanged. AC3 was re-checked with PUB-050's sampled voice examples: worst case 471 tokens (`test_ac3_holds_with_pub050_sampled_voice_examples`).
- **Legacy sidecars:** an override publish before this change could leave the social caption on line 1 (the removed `sd_caption or published_caption` fallback). A caption-generation rewrite without a new SD prompt (workflow or web Analyze) now drops such a line: `read_existing_sd_line` treats a line 1 equal to the recorded `caption` or a `caption_submitted` value as no SD prompt (`test_keep_existing_sd_line_skips_a_legacy_social_caption_on_line_1`). An override publish (`update_sidecar_with_caption`) still copies line 1 as-is, and sidecars nobody rewrites keep it; no migration sweeps old files. A forced web refresh deliberately regenerates and replaces operator captions, as on main (SD-off tenants now see this too, since they get sidecars).
- **Out of scope:** `scripts/vision_token_benchmark.py` sends `vision.user` only, so it no longer asks for `sd_caption`.
- **#171 (closed in a follow-up PR):** `_sanitize_analysis_field` no longer defaults `max_len` to the pre-#81 cap of 50; the cap is a required argument (`test_sanitize_analysis_field_requires_an_explicit_cap`).
