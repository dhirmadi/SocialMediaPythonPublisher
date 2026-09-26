# Implementation Handoff: PUB-051 — Caption Prompt and Register Repair

**Hardened:** 2026-09-25
**Status:** Ready for implementation

## For Claude Code

### Test-first targets

| AC | Test file | Test name (exact function) |
|----|-----------|-----------------------------|
| AC1 | `publisher_v2/tests/test_caption_angle_rotation.py` | `test_each_platform_receives_exactly_one_angle_per_call` |
| AC1 | `publisher_v2/tests/test_caption_angle_rotation.py` | `test_angle_rotates_across_three_renders_using_stored_column` |
| AC1 | `publisher_v2/tests/test_caption_angle_rotation.py` | `test_regeneration_picks_a_different_angle_than_the_rejected_draft` |
| AC2 | `publisher_v2/tests/test_ai_prompt_payload.py` | `test_no_closing_pattern_line_is_ever_rendered` |
| AC2 | `publisher_v2/tests/test_ai_prompt_payload.py` | `test_at_most_two_openings_to_avoid_appear_per_platform` |
| AC3 | `publisher_v2/tests/test_ai_prompt_payload.py` | `test_user_message_under_500_tokens_with_history_and_six_examples` |
| AC3 | `publisher_v2/tests/test_ai_prompt_payload.py` | `test_analysis_prose_contains_no_hex_colour_or_snake_case_tag` |
| AC4 | `publisher_v2/tests/test_ai_multi_caption.py` | `test_caption_call_requests_platform_keys_only_no_sd_caption` |
| AC4 | `publisher_v2/tests/test_ai_multi_caption.py` | `test_caption_call_sampling_params_match_configured_values` |
| AC5 | `publisher_v2/tests/test_ai_vision_analysis_telemetry.py` | `test_sd_caption_comes_from_the_neutral_register_vision_call` |
| AC5 | `publisher_v2/tests/test_ai_vision_analysis_telemetry.py` | `test_caption_facing_fields_carry_the_owner_persona_marker` |
| AC6 | `publisher_v2/tests/test_ai_vision_analysis_telemetry.py` | `test_senses_pool_prompt_text_differs_by_image_seed` |
| AC6 | `publisher_v2/tests/test_ai_vision_analysis_telemetry.py` | `test_caption_facing_fields_stay_out_of_sidecar_after_vision_restructure` |
| AC7 | `publisher_v2/tests/test_caption_context_intelligence.py` | `test_partial_retry_makes_zero_additional_ai_calls` |
| AC7 | `publisher_v2/tests/test_caption_history_db.py` | `test_caption_history_holds_one_row_per_successfully_published_platform_only` |
| AC8 | `publisher_v2/tests/test_ai_error_paths.py` | `test_non_json_vision_reply_retried_once_at_same_resolution_before_fallback` |

AC9 is a verification step, not a `pytest` AC — do not invent a test name for it (see the
spec's Implementation Notes). Record the harness table in each of the three PR bodies
(#191, #192, #194) instead.

The **Test name** column is the exact `pytest` function name Claude Code must create. AC1,
AC2, AC3, AC4, AC5, AC6, and AC7 each span two or three tests for the reasons given inline in
the spec (distinguishable failure signals for genuinely separate behaviors). If a different
name is genuinely clearer, record the actual name used in `PUB-051_summary.md` next to the AC
it satisfies. Existing test files (`test_ai_prompt_payload.py`, `test_ai_multi_caption.py`,
`test_ai_vision_analysis_telemetry.py`, `test_ai_error_paths.py`, `test_caption_history_db.py`,
`test_caption_context_intelligence.py`) already exist in this repo and cover adjacent behavior —
add to them rather than creating parallel files, except `test_caption_angle_rotation.py`, which
is new (the old `TestStructureDirectiveRotation` class in `test_caption_similarity.py` tests the
mechanism this item deletes; migrate/replace it there too, see Files below).

### The content-angle pool (AC1)

The spec's example pool (`sensation`, `moment`, `craft`, `atmosphere`, `direct_address`) is a
suggestion, not a mandate — pick names that describe *what the caption dwells on*. Keep the
existing `STRUCTURE_DIRECTIVES`-style shape: an ordered `dict[str, str]` (key → one-line
directive text), at least five entries, order used as the deterministic tie-break exactly like
today. Record the actual pool chosen in the summary doc.

**Rotation contract change from today's `pick_structure_directive`:** the old function
reverse-classified free caption text into a bucket (`classify_caption_structure`) because
nothing stored the original choice. This item removes that reverse-classification entirely —
the rotation must read the `angle` value stored per history row (via the new `CaptionStore`
surface, see Scope) and pick the least-recently-used key directly, falling back to "never used"
for `NULL` angles (old rows, or rows from before this migration). Do not keep
`classify_caption_structure`-style heuristics as a fallback for existing angle values — only for
the true-NULL case.

### Fixing the caption-history filter (AC7)

Today's bug, concretely: `core/workflow.py`'s `caption_history_saved` block builds
`published_captions` by iterating `enabled_publishers` unconditionally (every configured
publisher, regardless of whether *that* publisher's `publish_results` entry succeeded) —
see the block starting `for p in enabled_publishers:` before `_caption_store.save_captions_batch`.
Fix: filter to `p for p in enabled_publishers if publish_results.get(p.platform_name) and
publish_results[p.platform_name].success` (or equivalent) before building `published_captions`
and `truncation_info`. `any_success`/`partial` are already computed just above this block —
reuse `publish_results` directly rather than adding a new flag.

### The owner-persona marker (AC5)

Pin a fixed, content-independent sentinel — e.g. `OWNER_PERSONA_MARKER = "OWNER-VOICE SECTION:"`
— as a module-level constant in `services/ai.py`. It must appear in whichever system message
governs `sensory_detail`/`mood_note`: the entire system message of a second vision call (two-call
design), or a clearly delimited section within one combined system message (single-call
two-register design). Writing this test *before* the persona copy exists means asserting on the
marker's presence, not on the actual persona wording — the wording is a content decision for the
developer phase, the marker's existence is the structural contract this AC pins now.

### Mock boundaries

| External service | Mock strategy | Existing fixture/pattern |
|-------------------|---------------|---------------------------|
| OpenAI (caption call) | `unittest.mock.patch` recording `chat.completions.create(**kwargs)` | `test_ai_prompt_payload.py`, `test_ai_multi_caption.py` already do this — extend, don't replace |
| OpenAI (vision call(s)) | Fake client returning canned JSON per call; assert AC5 via the `OWNER_PERSONA_MARKER` sentinel in the relevant system message, not free-text wording matching | `test_ai_vision_analysis_telemetry.py` |
| DB (`CaptionHistory`/`angle`) | In-memory SQLite via `aiosqlite`, same pattern as today | `test_caption_history_db.py`'s `db_session_factory`/`store` fixtures |
| Orchestrator + publishers (AC7 partial retry) | Real `WorkflowOrchestrator`, fake publishers (some forced to fail), fake OpenAI client counting calls across two full runs | `test_caption_context_intelligence.py` already runs the real orchestrator with fakes — extend it |
| Filesystem (sidecar, AC6) | Real sidecar read/write against a `tmp_path`-backed fake storage, same as existing sidecar tests | `test_archive_with_sidecar.py` / `test_alt_text.py` patterns |

### Files likely touched

| Area | Files to modify | Files to create |
|------|------------------|-------------------|
| Angle pool + rotation | `publisher_v2/src/publisher_v2/utils/captions.py` (replace `STRUCTURE_DIRECTIVES`/`classify_caption_structure`/`pick_structure_directive`; keep `excluded_directives` adapted to new keys) | `publisher_v2/tests/test_caption_angle_rotation.py` |
| Existing rotation tests | `publisher_v2/tests/test_caption_similarity.py` (`TestStructureDirectiveRotation` tests the deleted mechanism — replace or remove, and say which in the summary doc) | — |
| DB schema | `publisher_v2/src/publisher_v2/db/models.py` (`CaptionHistory.angle`), `publisher_v2/src/publisher_v2/db/caption_store.py` (`save_captions_batch` gains `angles_by_platform`; existing `fetch_recent_by_platform` return shape and its ~8 tests in `test_caption_history_db.py` stay unchanged) | `publisher_v2/alembic/versions/004_add_caption_angle_column.py` (or next free number — check for any migration added by concurrent work); a new `fetch_recent_with_angles_by_platform` (or similar) sibling method on `CaptionStore` for the angle-aware read the rotation needs |
| Prompt assembly | `publisher_v2/src/publisher_v2/services/ai.py` (`_build_multi_prompt`, `build_analysis_context`, `build_platform_block`, `build_history_block`, `generate_multi_with_sd` (deleted in implementation — see summary), sampling constants near the top of the file, `_apply_similarity_gate`/`_generate_once` — must track the angle just chosen per platform per attempt so a regeneration excludes it, `create_multi_caption_pair_from_analysis`'s return arity gains the chosen angle per platform) | — |
| Caption-service callers | `publisher_v2/src/publisher_v2/core/workflow.py:604` and `publisher_v2/src/publisher_v2/web/service.py:909` (both unpack `create_multi_caption_pair_from_analysis`'s new return arity — update together, this is an internal contract, not a public API, but only safe if both callers move in the same change) | — |
| Vision register | `publisher_v2/src/publisher_v2/services/ai.py` (`VisionAnalyzerOpenAI.analyze`/`_analyze_core`, `_DEFAULT_VISION_*` constants — remove, nothing else needs them), `publisher_v2/src/publisher_v2/config/static/ai_prompts.yaml` (`vision.system`/`vision.user`, new owner-persona prompt with the `OWNER_PERSONA_MARKER` sentinel) | — |
| SD-caption fate | `publisher_v2/src/publisher_v2/services/ai.py:895-964` (`CaptionGeneratorOpenAI`'s `sd_caption_system_prompt`/`sd_caption_role_prompt`/`sd_caption_brief`/`sd_caption_model` resolution) and `ai_prompts.yaml`'s `sd_caption:` block — decide and state in the #192 PR body: removed as dead code once the multi-platform path no longer calls `generate_multi_with_sd` for `sd_caption` (outcome: `generate_multi_with_sd`/`sd_caption_brief` deleted; the `sd_caption_*` resolution kept for `generate_with_sd` — see summary), or kept alive because the single-platform fallback (`generate_with_sd`/`create_caption_pair_from_analysis`) still uses it | — |
| Register/copy | `publisher_v2/src/publisher_v2/config/static/ai_prompts.yaml` (`caption.system`, `caption.rules` — every `DEFAULT_TELLS_LEXICON` pattern gets a "write X instead" line, per-platform `style` stances) | — |
| Retry/history plumbing | `publisher_v2/src/publisher_v2/core/workflow.py` (`caption_history_saved` block around line 785 — filter `enabled_publishers` by `publish_results` success before building `published_captions`; partial-retry sidecar read path) | — |
| Docs | `docs_v2/07_AI/AI_PROMPTS_AND_MODELS.md` (rope-specific persona moved here as a tenant `system_prompt` example, per Scope) | — |

**Sequencing reminder:** AC4 (#191) and AC5 (#192) must land in the same deploy — see the spec's
Scope note on the `sd_caption` regression window. Plan the PR sequence accordingly; do not treat
#191/#192/#194 as independently mergeable in isolation.

### Non-negotiables for this item

- [ ] Preview mode: N/A — no publish/archive/cache-mutation behavior in this item; preview mode's existing guarantees are unaffected by prompt/register changes.
- [ ] Secrets: no new secrets; the vision/caption calls continue to read model config the existing way.
- [ ] Auth: N/A (no web endpoint changes).
- [ ] Async hygiene: **correction from the original draft** — `VisionAnalyzerOpenAI` has no `_rate_limiter` at all today (`AIService.__init__` wires the shared limiter into `self.generator` only; `core/workflow.py:486` calls `analyzer.analyze(...)` completely unwrapped). If AC5/AC6 add a second vision-stage call, it is **not** protected by anything just by matching an existing pattern, because no such pattern exists on the analyzer side. Wiring the rate limiter into the vision analyzer is a pre-existing gap, not this item's job to fix — see the spec's Risks section. Do not claim rate-limiter coverage for the new call in the summary doc unless you actually added the wiring and call it out as an explicit, deliberate addition beyond this item's stated scope.
- [ ] Coverage: ≥80% on `utils/captions.py`, `services/ai.py`, `db/caption_store.py`; ≥85% overall maintained.
- [ ] No new runtime dependency — AC3's token count is `len(prompt) / 4`, not `tiktoken`.
- [ ] Backward compatibility: the `angle` column is additive/nullable; existing `CaptionHistory` rows and any code reading them without an `angle` must keep working unchanged.

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-051_caption-prompt-and-register-repair.md
```
