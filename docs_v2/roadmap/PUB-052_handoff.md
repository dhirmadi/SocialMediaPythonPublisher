# Implementation Handoff: PUB-052 — Caption Candidate Selection and Model Trial

**Hardened:** 2026-09-26
**Refreshed:** 2026-09-27 (post-PUB-051 landing)
**Status:** Ready for implementation

## For Claude Code

### Sequencing

Both dependencies are now **Done**: PUB-049 (caption evaluation harness) and PUB-051 (caption
prompt and register repair). The code references below target the **post-PUB-051** codebase
shape, which is now the actual state of the repo.

**PUB-051 landed the following changes relevant to this item:**
- `pick_structure_directive` / `STRUCTURE_DIRECTIVES` → replaced by `pick_content_angle` /
  `CONTENT_ANGLES` in `utils/captions.py`
- `classify_caption_structure` → removed entirely
- `_generate_once` is now a closure inside `create_multi_caption_pair_from_analysis` (~line 1800)
- `_apply_similarity_gate` still exists (~line 1828) with the same trigram Jaccard gate — this
  is what this item deletes
- `excluded_directives` still exists in `services/ai.py` (~line 870) — adapted for
  `CONTENT_ANGLES` keys
- Content angle tracking is stored via `CaptionStore` with an `angle` column on `CaptionHistory`
- Both web and cron now call `fetch_recent_with_angles_by_platform` with
  `limit=angle_history_depth(window_size)`, but the text-based caption window is still
  `window_size=3` (this item changes that default to 30)

**Orphaned test note:** PUB-051 shipped
`test_regeneration_picks_a_different_angle_than_the_rejected_draft` in
`test_caption_angle_rotation.py` — it tests the angle-on-rejection mechanism inside
`_apply_similarity_gate`. Since this item deletes that entire gate, this test must be removed
(not repurposed) as part of the "Tests to remove or repurpose" section below.

### Test-first targets

| AC | Test file | Test name (exact function) |
|----|-----------|-----------------------------|
| AC1 | `publisher_v2/tests/test_caption_candidate_selection.py` | `test_near_duplicate_candidate_is_never_selected` |
| AC2 | `publisher_v2/tests/test_caption_candidate_selection.py` | `test_default_model_makes_exactly_one_n3_caption_request` |
| AC3 | `publisher_v2/tests/test_caption_candidate_selection.py` | `test_n_unsupported_fallback_makes_three_separate_temperature_calls` |
| AC4 | `publisher_v2/tests/test_caption_candidate_selection.py` | `test_selection_is_deterministic_and_ties_break_by_lowest_index` |
| AC5 | `publisher_v2/tests/test_caption_candidate_selection.py` | `test_caption_candidate_selected_logs_per_candidate_scores_and_winner_index` |
| AC6 | `publisher_v2/tests/test_caption_candidate_selection.py` | `test_similarity_threshold_and_regeneration_loop_no_longer_exist` |
| AC7 | `publisher_v2/tests/test_caption_candidate_selection.py` | `test_condense_runs_once_against_the_winning_candidate_only` |
| AC8 | `publisher_v2/tests/test_caption_context_intelligence.py` | `test_web_and_cron_fetch_the_same_history_depth_for_selection` |

AC9 and AC10 are verification steps, not `pytest` ACs — do not invent test names for them (see
the spec's Implementation Notes and the PUB-049/PUB-051 precedent for AC9/AC-verification steps).
Record the harness table (AC9) in the #193 PR body; record the blind-reading table (AC10) on the
#195 trial issue.

The **Test name** column is the exact `pytest` function name Claude Code must create — the only
spec-to-test traceability link this contract relies on. If a different name is genuinely clearer,
record the actual name used in `PUB-052_summary.md` next to the AC it satisfies.

`test_caption_candidate_selection.py` is new. `test_caption_context_intelligence.py` and
`test_caption_similarity.py`/`test_caption_similarity_telemetry.py` already exist and cover
adjacent/deleted behavior — see "Tests to remove or repurpose" below.

### The selector contract (AC1, AC4, AC5)

- Weighting: `score = tells_rate * 2 + cosine_to_history`, lowest wins. `tells_rate` for a single
  candidate is `caption_metrics.tells_lexicon_hit_rate([candidate_text])` (0.0 or 1.0).
  `cosine_to_history` is `caption_metrics.tfidf_bigram_cosine(candidate_text, history_for_platform)`
  where `history_for_platform` is the **full 30-caption fetch**, not the prompt's capped-to-2
  openings-to-avoid list.
- Weights are config, not hardcoded constants: add `CaptionSelectionConfig` to
  `config/static_loader.py` (same `BaseModel` pattern as `CaptionHistoryConfig`, same
  `ai_prompts.yaml`-backed loading) with `tells_weight: float = 2.0` and
  `cosine_weight: float = 1.0`. The score formula becomes
  `tells_rate * tells_weight + cosine_to_history * cosine_weight`.
- Selection is per platform, independently, over that platform's three candidate texts (one text
  per API choice/temperature call, all for the same platform key in each response).
- Ties (exactly equal combined scores) break by the lowest candidate index (0, 1, 2 — the order
  the three candidates were generated/received in). No random tiebreak, no seed parameter
  anywhere in the selector.
- `caption_candidate_selected` (new event, AC5) carries per platform: each candidate's index,
  combined score, `tells_rate` component, and `cosine_to_history` component, plus the winning
  candidate's index. One log call per platform per selection run.
- `caption_similarity` (kept event name) changes its payload meaning: `max_similarity` becomes
  the **winning** candidate's `cosine_to_history` score (not a trigram score); `history_size`
  stays as `len(history.get(platform, []))`; drop the `regenerated` field entirely (no
  regeneration exists to report on).

### The n=3 vs. three-temperatures contract (AC2, AC3)

- Default/primary path: one `chat.completions.create(...)` call with `n=3` (plus the existing
  `response_format={"type": "json_object"}`, and the PUB-051 sampling params:
  `temperature=0.9`, `frequency_penalty=0.3`, `presence_penalty=0.6`). Three choices come back
  in one response; extract each platform's candidate text from each of the three
  `resp.choices[i].message.content` JSON payloads.
- Fallback path (AC3): only exercised when the configured model is known not to support `n>1`
  with JSON mode. Implement as three separate `chat.completions.create(...)` calls, each with
  `n=1` and a distinct temperature (three temperature values — pick three that bracket the
  default, e.g. the default ± 0.15, and document the exact three in the summary doc). This is
  in-scope, deterministic code with its own test (AC3) — it is not the "owner-judged, no
  code" AC9/AC10 territory.
- State in the #193 PR body which path was implemented as primary for the currently configured
  default model, and confirm whether that model actually supports `n>1` (verify against the
  OpenAI API docs/changelog for the exact model string in `config/schema.py`'s `caption_model`
  default at implementation time — do not assume gpt-4o-mini's behavior is unchanged if the
  default model string has moved).

### Removing the gate (AC6) and its test collateral

- Delete `CAPTION_SIMILARITY_THRESHOLD` (line 121) and the entirety of `_apply_similarity_gate`
  (~line 1828) in `services/ai.py`, plus the `_generate_once` closure's
  `diversity_clause`/`directives` parameters and the call sites that pass them. The
  angle-on-rejection tracking that PUB-051 added inside `_apply_similarity_gate` (retry angle
  re-assignment via `pick_content_angle` with the rejected angle excluded, ~lines 1860-1878)
  must also be deleted — don't leave it dead.
- AC6's "codebase search" test: assert `CAPTION_SIMILARITY_THRESHOLD` does not appear in
  `services/ai.py`'s source (e.g. read the file text and assert the string is absent), and that
  `_apply_similarity_gate` either no longer exists as a name or, if kept as a thin wrapper that
  just logs `caption_similarity`, no longer contains a retry/regeneration branch — pick one
  design and assert on it directly (e.g. `hasattr`/`inspect.getsource` check), not just a
  docstring search.
- Tests to remove or repurpose in the same change:
  - `TestSimilarityGate` class in `test_caption_similarity.py` — tests the deleted gate directly.
  - `test_caption_similarity_telemetry.py` — tests the old `caption_similarity` payload shape
    (`regenerated` field, trigram-based `max_similarity`); rewrite its assertions for the new
    payload shape (selector's `cosine_to_history`, no `regenerated`), don't just delete the file,
    since `caption_similarity` telemetry itself is kept (Scope).
  - `test_regeneration_picks_a_different_angle_than_the_rejected_draft` in
    `test_caption_angle_rotation.py` — this test (shipped by PUB-051) exercises the
    angle-on-rejection mechanism inside `_apply_similarity_gate`, which this item deletes
    entirely. **Remove it** (do not repurpose — the mechanism is gone, not renamed).
  - Also check `test_caption_context_intelligence.py` for
    `test_the_gate_picks_the_retry_directive_with_the_draft_first` (~line 731) — it references
    the regeneration-angle mechanism and may need removal or updating.
  - Do **not** touch `trigram_jaccard`'s own unit tests in `test_caption_similarity.py` (the
    ones that call `trigram_jaccard` directly, not through the gate) or
    `test_clone_set_flagged_by_new_metrics_not_by_trigram` in `test_caption_metrics.py` — both
    must keep passing unchanged.

### History depth (AC8)

- `config/static_loader.py`: change `CaptionHistoryConfig.window_size`'s default from `3` to
  `30` (the `ge=0, le=50` bound already accommodates 30; no bound change needed).
- **Post-PUB-051 reality:** both `core/workflow.py` (~line 606) and `web/service.py` (~line 955)
  now call `fetch_recent_with_angles_by_platform` with
  `limit=angle_history_depth(window_size)`. The `angle_history_depth` function (in
  `utils/captions.py`) returns `max(window_size, len(CONTENT_ANGLES))`, ensuring at least one
  full angle-pool cycle is fetched. When `window_size` moves to 30, both paths automatically
  fetch `max(30, 5) = 30` rows for angles — no code change needed in the call sites, just the
  config default.
- The text-based caption-history window is still sliced to `window_size` after the fetch
  (e.g. `caption_history = {p: [text for text, _a in items][:window] ...}` in `web/service.py`
  ~line 958). The selector in this item should use the **full** 30-row fetch for its
  cosine-to-history scoring (not the sliced prompt window), while the prompt's
  openings-to-avoid list stays at 2 (the existing constraint from PUB-051).
- Update `test_caption_history_defaults` (`test_caption_context_intelligence.py`) — it currently
  asserts `cfg.window_size == 3`; change the assertion to `30` and update the comment that
  explains the old `8 -> 3` (#82) rationale.
- New test (AC8): a test that drives both the real `web/service.py` fetch call and the real
  `core/workflow.py` fetch call (fake `CaptionStore`/DB underneath) and asserts both request
  `limit=30`.

### Condense-once-on-winner (AC7)

- Today's condense pass (`_condense_caption`, PUB-046) already runs per platform on overshoot.
  Scope requires it run **only on the platform's selected winner**, never on the two non-winning
  candidates — i.e., selection must complete before any condense call is made, and only one
  condense call per overshooting platform (not per candidate).

### Mock boundaries

| External service | Mock strategy | Existing fixture/pattern |
|-------------------|---------------|---------------------------|
| OpenAI (caption call, n=3 path) | `unittest.mock.patch` returning a `ChatCompletion` with 3 `choices`, each a JSON payload with all enabled platform keys | `test_ai_multi_caption.py` already builds fake multi-choice-shaped responses — extend, don't replace |
| OpenAI (caption call, fallback path) | `unittest.mock.patch` recording 3 separate `create(...)` calls, each `n=1` | new in `test_caption_candidate_selection.py` |
| OpenAI (condense call) | `unittest.mock.patch`, same pattern as existing condense tests | existing condense test file(s) |
| DB (`CaptionStore.fetch_recent_with_angles_by_platform`) | fake/in-memory store returning up to 30 canned caption+angle rows per platform | `test_caption_history_db.py` fixtures |
| Web + cron history-depth parity (AC8) | real `web/service.py` + real `WorkflowOrchestrator`, fake `CaptionStore` recording the `limit` kwarg each call site passed | `test_caption_context_intelligence.py` already runs the real orchestrator with fakes |

### Files likely touched

| Area | Files to modify | Files to create |
|------|------------------|-------------------|
| Selector | `publisher_v2/src/publisher_v2/services/ai.py` (new selector function; `_generate_once` closure and `_apply_similarity_gate` replaced; `_assign_angles`/`_angle_directives`/`excluded_directives` kept; `CAPTION_SIMILARITY_THRESHOLD` deleted), `publisher_v2/src/publisher_v2/utils/caption_metrics.py` (no change expected — only consumed, not modified) | `publisher_v2/tests/test_caption_candidate_selection.py` |
| Config | `publisher_v2/src/publisher_v2/config/static_loader.py` (`CaptionSelectionConfig` new; `CaptionHistoryConfig.window_size` default 3 -> 30), `publisher_v2/src/publisher_v2/config/static/ai_prompts.yaml` (new `caption_selection:` block for the two weights) | — |
| History depth parity | `publisher_v2/src/publisher_v2/web/service.py` (already passes `limit=angle_history_depth(window_size)` post-PUB-051; only the `window_size` default in `config/static_loader.py` needs to change from 3 to 30) | — |
| Test collateral | `publisher_v2/tests/test_caption_similarity.py` (remove `TestSimilarityGate`, keep `trigram_jaccard` unit tests), `publisher_v2/tests/test_caption_similarity_telemetry.py` (rewrite for new `caption_similarity` payload), `publisher_v2/tests/test_caption_angle_rotation.py` (remove `test_regeneration_picks_a_different_angle_than_the_rejected_draft` — PUB-051 shipped it), `publisher_v2/tests/test_caption_context_intelligence.py` (`test_caption_history_defaults` assertion 3 -> 30; check `test_the_gate_picks_the_retry_directive_with_the_draft_first` for gate-removal impact; new AC8 test) | — |
| Docs | `docs_v2/07_AI/AI_PROMPTS_AND_MODELS.md` (`CaptionSelectionConfig`, `window_size` default, `caption_candidate_selected` event) | — |

### Non-negotiables for this item

- [ ] Preview mode: N/A — no publish/archive/cache-mutation behavior in this item; preview mode's existing guarantees are unaffected by candidate-selection changes.
- [ ] Secrets: no new secrets; model trial (AC10) reuses the existing OpenAI credential path.
- [ ] Auth: N/A (no web endpoint changes).
- [ ] Async hygiene: no new blocking calls; the extra two candidate choices ride the same rate-limited `chat.completions.create` call (n=3) or the same rate-limited call repeated three times (fallback path) — both already pass through `AIService`'s shared `AsyncRateLimiter`, so no new wiring is needed here.
- [ ] Coverage: ≥80% on `services/ai.py`, `utils/caption_metrics.py` (consumption only), `config/static_loader.py`; ≥85% overall maintained.
- [ ] No new runtime dependency.
- [ ] Backward compatibility: `caption_similarity`'s event name is preserved (dashboards keep working); its field semantics change (documented above) — note this explicitly in the #193 PR body since it's a silent payload change under an unchanged event name.

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-052_caption-candidate-selection.md
```
