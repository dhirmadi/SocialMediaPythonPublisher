---
name: prompt-register-review-traps
description: Caption prompt/persona/vision review traps (#138) — tenant system_prompt vs caption.rules append, vision 512 cap, directive-vs-brief contradictions, stale PV2_STATIC_CONFIG_DIR, vacuous plural/singular assertions
metadata:
  type: project
---

Findings from the #138 caption-register reviews (2026-09-19/20) that recur on any prompt diff:

- A tenant `system_prompt` REPLACES static `caption.system` wholesale. #138 round 3 fixed this by
  appending a separate `caption.rules` key to whichever persona is in force. The protection lives in
  the SHIPPED yaml: a `PV2_STATIC_CONFIG_DIR` file replaces ai_prompts.yaml wholesale (no per-key
  merge, `load_static_config`), so a custom dir without `rules` silently loses the banned list again.
- Vision `max_tokens` was 512, now 1024 (`vision_max_completion_tokens` getattr default, no schema
  field). Truncated JSON -> json_decode_error; fakes never catch it.
- STRUCTURE_DIRECTIVES rotation can contradict platform briefs; `excluded_directives(spec)` handles
  short_line (word-budgeted) and observation (closing=question). Check any new directive/brief pair.
- `PlatformCaptionStyle` strips (does NOT reject) a stale `examples:` key via a mode="before"
  validator + `static_caption_examples_ignored` warning. Raising there took down CLI + web lifespan.
- sd_caption shares build_analysis_context, so caption-facing fields also feed the SD/.txt prompt.
- smart_truncate: old vs new differ ONLY when the sentence end sits at index max_length-1.
- **Vacuous assertion trap**: the diff renamed "Recent closing patternS to avoid" -> singular, but
  `test_mandated_closing_skips_closing_pattern_constraint` still asserts `"closing patterns" not in
  block` — it cannot fail. Grep the exact asserted substring against the source after any prompt
  wording rename.
- Untested-by-construction in that diff (all mutation survivors): the per-offender `directives`
  kwarg plumbed AIService -> generator (dropping it leaves every test green, because
  build_platform_block re-picks from history anyway); the regeneration clause wording; the
  `End with a {closing}.` line; `role_prompt_single` honouring a tenant custom role.
- `_build_multi_prompt` promotes `spec.examples` into the hardened block when the caller passes no
  `voice_examples`. `[]` and `None` are treated alike, so a voice profile fully dropped by
  `truncate_voice_profile_to_budget` comes back untruncated through the promotion path.

- **Gate ordering is untested (round 3 survivor):** `_apply_similarity_gate` picks the offender's
  retry directive from `[captions[platform], *history[platform]]`. Flipping it to
  `[*history, captions[platform]]` leaves the WHOLE suite green. The existing regeneration fixture
  has a 1-entry history (draft == history[0]), so both orderings classify identically; the
  round-3 test only exercises `pick_structure_directive` directly. A discriminating end-to-end
  fixture: telegram-only, 5-caption history covering every structure key, draft == the "short line"
  entry (similarity 1.0). Draft-first yields "Open with a plain declarative statement.",
  draft-last yields "Open with a short sensory fragment...".

**Why:** these pass all tests (fake OpenAI) but are production-visible.
**How to apply:** on any ai_prompts.yaml / services/ai.py prompt diff, check these explicitly.
See also [[caption-sidecar-review-traps]], [[mutation-check-review-technique]].
