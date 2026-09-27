# PUB-081: Publish Reuses the Sidecar Analysis When Every Caption Is Supplied

| Field | Value |
|-------|-------|
| **ID** | PUB-081 |
| **Category** | AI |
| **Priority** | P2 |
| **Effort** | S |
| **Status** | Proposal |
| **Dependencies** | PUB-051 |

## User Story

As the owner, I want a web publish in which I supplied every caption to reuse the analysis that Analyze
already saved in the sidecar, so that I stop paying for a second vision call on every publish.

## Problem

Tracked in [#250](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/250). The first FetLife
publish (2026-09-27, `210724_FL_9700.jpg`) ran vision twice. The first call was in Analyze. The second
came in Publish with `caption_overrides` for every platform, and it cost 4.8s of a 13.4s publish.

1. **The reuse path excludes overrides.** `wants_ai_captions` (`core/workflow.py:482-484`) is False as
   soon as any override is set. The PUB-051 reuse at `:485-490` therefore runs only for a partial retry
   with no overrides. It also sits inside the lease block (`:451`), which runs only when a publish store
   is configured.
2. **Vision runs anyway.** The analyzer is called at `:493-510` whenever `reused_captions is None`. The
   override branch (`:550-561`) logs `ai_skipped=True`, but vision has already run by then.
3. **The only consumer of that second call is publisher context.** `_build_publisher_context`
   (`:1275-1284`) passes `analysis_tags` and, with `FEATURE_ALT_TEXT`, `alt_text`. The email confirmation
   reads the tags (`services/publishers/email.py:150-153`). No publisher reads `alt_text` today.
4. **The helper exists but is all-or-nothing.** `_reuse_generated_captions` (`:1242-1273`) rebuilds
   `ImageAnalysis(tags, alt_text)` from sidecar metadata, but it returns something only when
   `caption_generated` covers every platform.

## Desired Outcome

In a run that will publish, when the operator supplied every caption, the workflow reads the sidecar once
before the AI stage. If that sidecar holds usable analysis, publish uses it and makes zero OpenAI calls.
Otherwise, or if the read fails, vision runs exactly as it does today.

## Decision (owner-confirmed 2026-09-27)

The owner confirmed the drafted choices: a legacy single `caption_override` also skips vision, and a
sidecar with no `sha256` is accepted.


- **"Every caption"** means a non-blank override for every platform in `publish_targets`, or a non-blank
  legacy `caption_override`, which already applies to every platform.
- **"Usable"** means that `metadata.tags` is a non-empty list, since the email confirmation needs it.
  `alt_text` is taken when present and never required. A sidecar with no tags (for example, one written
  with extended metadata off) falls back to vision.
- **Stale:** if `metadata.sha256` is present and differs from the run's `selected_hash`, the sidecar
  describes other bytes, so vision runs. An absent `sha256` is accepted, because web Analyze writes
  `sha256=""` (`web/service.py:1045`) and `build_metadata_phase1` omits the key when it is empty.
- **One sidecar read.** The early read's view feeds `_override_angles`. Its raw text is passed to
  `update_sidecar_with_caption` through a new optional argument, so the existing single-download test
  still holds.
- **Gating:** the new path runs only when `will_publish` is True and `publish_targets` is non-empty. This
  check sits outside the publish-store block, so it covers both the store and no-store configurations.

## Scope

**In scope:**
- Split `_reuse_generated_captions` so the metadata-to-`ImageAnalysis` rebuild is its own helper, used by
  both the PUB-051 retry path and a new metadata-only reuse method.
- In `execute`, add the gated early read and skip the vision block when it yields an analysis. Log
  `feature_analyze_caption_skipped` with `reason="analysis reused from sidecar"`, and leave
  `vision_analysis_ms` null. No new event names.
- `update_sidecar_with_caption` accepts the already-read sidecar text and skips its own download.

**Out of scope:**
- Making web Analyze record `sha256`, which would give a stricter staleness check (possible follow-up).
- Partial overrides, which the web layer already rejects (`web/service.py:1086-1096`).
- The cron/CLI path. It never passes overrides, so its behaviour is unchanged.
- Preview, dry-publish and debug, which are unchanged. They never reach the new read.
- Stage extraction (PUB-058).

## Acceptance Criteria

- AC1: Given overrides for every publish target and a sidecar whose metadata holds tags and alt text,
  when publish runs through the real orchestrator with a counting fake OpenAI, then vision and caption
  calls are both zero, the publish succeeds, and `feature_analyze_caption_skipped` carries
  `reason="analysis reused from sidecar"`.
- AC2: Given AC1, when publishers are called, then `context["analysis_tags"]` equals the sidecar tags.
  `context["alt_text"]` equals the sidecar alt text when `FEATURE_ALT_TEXT` is on and is absent when it
  is off.
- AC3: Given full overrides and no sidecar, when publish runs, then vision runs once, as today.
- AC4: Given full overrides and a sidecar whose metadata has no `tags`, when publish runs, then vision
  runs once.
- AC5: Given full overrides and a sidecar whose `metadata.sha256` differs from the run's hash, when
  publish runs, then vision runs once.
- AC6: Given full overrides and a sidecar download that raises, when publish runs, then vision runs once,
  `analysis_reuse_failed` is logged at WARNING with no sidecar content, and the publish succeeds.
- AC7: Given overrides that omit one publish target (workflow called directly), when publish runs, then
  vision runs once.
- AC8: Given a legacy single `caption_override` and a usable sidecar, when publish runs, then vision
  calls are zero.
- AC9: Given preview, dry-publish or debug with full overrides, when the run executes, then vision runs
  as today and the sidecar is not read before the AI stage.
- AC10: Given AC1, when the run completes, then the sidecar was downloaded exactly once. The unedited
  override's angle is still recorded, and the existing `test_override_publish_reads_the_sidecar_once`
  passes unedited.
- AC11: Given a PUB-051 partial retry without overrides, when it runs, then it still makes zero AI calls
  (the existing `test_partial_retry_makes_zero_additional_ai_calls` passes unedited).
- AC12: Given the real web app, when Analyze runs and Publish follows with every platform's caption, then
  the analyzer was called exactly once across both requests.
- AC13: Given this item ships, when its implementing PR merges, then #250 is closed with `Closes #250`
  in the PR body.

## Test-first targets

| AC | Test |
|----|------|
| AC1 | `publisher_v2/tests/test_workflow_override_analysis_reuse.py::test_full_overrides_with_sidecar_analysis_make_zero_openai_calls` |
| AC2 | `publisher_v2/tests/test_workflow_override_analysis_reuse.py::test_publishers_get_sidecar_tags_and_alt_text_when_analysis_is_reused` |
| AC3 | `publisher_v2/tests/test_workflow_override_analysis_reuse.py::test_full_overrides_without_sidecar_run_vision_once` |
| AC4 | `publisher_v2/tests/test_workflow_override_analysis_reuse.py::test_sidecar_without_tags_falls_back_to_vision` |
| AC5 | `publisher_v2/tests/test_workflow_override_analysis_reuse.py::test_sidecar_for_other_bytes_falls_back_to_vision` |
| AC6 | `publisher_v2/tests/test_workflow_override_analysis_reuse.py::test_sidecar_read_failure_falls_back_to_vision_and_warns` |
| AC7 | `publisher_v2/tests/test_workflow_override_analysis_reuse.py::test_overrides_missing_a_target_still_run_vision` |
| AC8 | `publisher_v2/tests/test_workflow_override_analysis_reuse.py::test_legacy_single_override_reuses_sidecar_analysis` |
| AC9 | `publisher_v2/tests/test_workflow_override_analysis_reuse.py::test_preview_dry_and_debug_do_not_read_sidecar_before_vision` |
| AC10 | `publisher_v2/tests/test_workflow_override_analysis_reuse.py::test_reused_analysis_publish_downloads_the_sidecar_once` |
| AC11 | `publisher_v2/tests/test_caption_context_intelligence.py::test_partial_retry_makes_zero_additional_ai_calls` (existing) |
| AC12 | `publisher_v2/tests/web/test_per_platform_captions_real_app.py::test_analyze_then_publish_with_every_caption_calls_vision_once` |

## Overlap with PUB-058

There is no functional overlap, only a question of sequencing. PUB-058 extracts `execute` into stages and
must preserve PUB-051's sidecar reuse. This item adds one more reuse rule to the analyze step. If this
item lands first, PUB-058's characterisation suite should add a "full-override publish reuses sidecar
analysis" scenario, and the Analyze stage should own the rule. If PUB-058 lands first, this item becomes
an edit to that stage, as PUB-058 AC6 (working rule 3) requires. Neither item blocks the other.

## Risks

- **Same-name replacement.** An image replaced under the same filename after an Analyze that stored no
  `sha256` would publish with old tags. Only the email confirmation tags line is affected; captions come
  from the operator.
- **Another branch in a long function** (see PUB-058). Keep it to one guarded call into a helper.

## References

- [#250](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/250): this item's issue
- PUB-051 (archive): partial-retry sidecar reuse, override angles, single sidecar read
- PUB-058: workflow stages and layering
- [#147](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/147): per-platform caption overrides
