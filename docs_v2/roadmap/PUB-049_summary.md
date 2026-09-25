# PUB-049 — Caption Evaluation Harness: Implementation Summary

**Status:** Implementation Complete
**Date:** 2026-09-22

## Files Changed

### Created
- `publisher_v2/src/publisher_v2/utils/caption_metrics.py` — the seven metric functions (nine scored
  values), `DEFAULT_TELLS_LEXICON` (one regex per line, one comment per pattern) and `STOPWORDS`.
- `scripts/caption_eval.py` — `--offline` / `--nightly` / `--generate-thresholds`, `main(argv) -> int`,
  the pure `generate_thresholds(scores)`, and `build_generator()` as the single OpenAI seam.
- `.github/workflows/caption-eval-nightly.yml` — `schedule` + `workflow_dispatch` only.
- `publisher_v2/tests/test_caption_metrics.py`, `publisher_v2/tests/test_caption_eval_script.py`
- `publisher_v2/tests/fixtures/captions/` — `README.md`, `clone_set.json`, `analyses/a01..a20.json`,
  `history/{telegram,email,instagram}.json`, plus the generated `snapshot.json` and
  `caption_eval_thresholds.json`.

### Modified
- `publisher_v2/src/publisher_v2/utils/captions.py` — `_words` promoted to public `words()` (with
  `_words = words` retained; `test_caption_tokenizer_unicode.py` still imports it), plus the shared
  `word_ngrams()` that `trigram_jaccard` and `caption_metrics` both build on. One tokenizer, one
  n-gram construction, as the spec requires.
- `scripts/caption_sample.py` — AC7 retirement (see below).
- `publisher_v2/tests/test_caption_sample_script.py` — AC7 test updates.
- `.github/workflows/code-quality.yml` — new `caption-eval` job on the existing triggers.

## Acceptance Criteria

- [x] **AC1** — clone set flagged by the new metrics, not by trigram (`test_clone_set_flagged_by_new_metrics_not_by_trigram`).
      Measured: tells rate **1.00** vs bar 0.01; worst pairwise TF-IDF cosine **0.0544** vs bar 0.0108;
      worst pairwise `trigram_jaccard` **0.0323**, under the 0.04 ceiling the spec's Problem section measured.
- [x] **AC2** — seven metrics, seven separate tests, each pinning a hand-computed value:
      `test_opener_closer_trigram_share_matches_hand_computed_value`,
      `test_sentence_and_word_count_variance_matches_hand_computed_value`,
      `test_two_sentence_emoji_rhythm_share_matches_hand_computed_value`,
      `test_tells_lexicon_hit_rate_matches_hand_computed_value`,
      `test_distinct_1_and_distinct_2_match_hand_computed_value`,
      `test_tfidf_bigram_cosine_to_history_matches_hand_computed_value`,
      `test_vision_field_content_word_overlap_matches_hand_computed_value`.
      Not collapsed into a parametrized test. Five were re-derived independently in review, including
      the TF-IDF literal `0.8173423172931453`.
- [x] **AC3** — `test_offline_mode_makes_zero_network_calls_and_completes_under_ten_seconds`,
      `test_offline_mode_fails_loudly_when_prompt_rendering_raises`.
      Measured **0.31s** wall clock against the ten-second cap; zero network calls confirmed by
      running with `socket.connect`/`create_connection`/`getaddrinfo` patched to raise.
- [x] **AC4** — `test_offline_mode_exits_nonzero_and_names_metric_on_threshold_regression`,
      `test_offline_mode_passes_cleanly_on_the_real_committed_snapshot_and_thresholds`,
      plus two tests added beyond the handoff table (see Deviations).
- [x] **AC5** — `test_nightly_mode_regenerates_snapshot_and_writes_diff_to_disk`,
      `test_nightly_mode_never_imports_or_calls_anything_github_shaped`.
- [x] **AC6** — `test_generate_thresholds_derives_bar_from_snapshot_scores_with_margin`.
- [x] **AC7** — `test_the_table_pairs_each_platform_and_scores_similarity`,
      `test_similarity_to_the_previous_image_is_reported_per_variant` (both updated).
      The "Delta" column and the "Mean similarity to the previous image" section are gone; the word
      "trigram" no longer appears in the rendered Markdown. `trigram_jaccard` itself is untouched and
      still used at `services/ai.py:1579` — deleting it is PUB-052's call, not this item's.

## Test Results

```
1817 passed, 1 skipped, 83 warnings in 83.09s
```

Verified on multiple independent random seeds (`pytest-randomly`): 70177, 424242, 555001, 2900400410,
4050879511, 2117687396, 733565177. No isolation defects.

## Quality Gates

| Gate | Result |
|------|--------|
| Format | ✅ 248 files already formatted |
| Lint | ✅ All checks passed |
| Type check | ✅ no issues in 65 source files |
| Tests | ✅ 1817 passed, 0 failed, 1 skipped |
| Coverage | ✅ `utils/caption_metrics.py` **93%**, `utils/captions.py` 96%, **total 92.82%** (gate: 85%) |

`scripts/caption_eval.py` is outside `[tool.coverage.run] source`, as `scripts/caption_sample.py` is
today. It is tested for correctness but is deliberately **not** claimed against the coverage gate.

## Derived Thresholds

`publisher_v2/tests/fixtures/captions/caption_eval_thresholds.json`, generated from the committed
snapshot and verified byte-identical on regeneration (md5 `44c3f13f477e627ab781a04a7d4c2b35`;
snapshot md5 `89960df08ca06dace60517d2218cb104`).

| Metric | Direction | Bar | Snapshot score |
|---|---|---|---|
| opener_closer_trigram_share | max | 0.0100 | 0.0000 |
| two_sentence_emoji_rhythm_share | max | 0.0100 | 0.0000 |
| tells_lexicon_hit_rate | max | 0.0100 | 0.0000 |
| tfidf_bigram_cosine | max | 0.0108 | 0.0098 |
| vision_field_overlap | max | 0.3096 | 0.2814 |
| sentence_count_variance | min | 0.3127 | 0.3475 |
| word_count_variance | min | 75.8660 | 84.2956 |
| distinct_1 | min | 0.4449 | 0.4943 |
| distinct_2 | min | 0.8235 | 0.9150 |

## Subagent Verdicts

- `test-engineer` (Red, three rounds) — 17 handoff-named tests plus two added; all confirmed failing
  for the right reason before implementation.
- `developer` (Green, three rounds) — implementation, plus two review-fix batches.
- `code-reviewer`: **PASS WITH NITS** — all 17 spec-pinned names present and non-vacuous; AC1/AC5/AC6
  artifacts verified by execution; four fixes re-verified by *mutation* (reverting each one confirmed
  the new test actually goes red). No pre-existing test loosened.
- `security-auditor`: **PASS WITH NITS** — no hard-coded secrets, no GitHub token in the script,
  `--offline` network isolation re-confirmed under patched sockets, bandit clean (4 pre-existing Lows
  in `caption_sample.py`, no new `nosec`).

All findings from both reviewers were routed back and resolved; none was downgraded to ship.

## Decisions and Deviations

1. **Thresholds file location** (handoff left this to Claude Code): `publisher_v2/tests/fixtures/captions/caption_eval_thresholds.json`,
   next to the `snapshot.json` it scores — spec Risks requires the two to agree the moment they land.
2. **`ZERO_BAR_EPSILON = 0.01`** — a deviation from the spec's literal "±10%". A multiplicative margin
   is degenerate at a score of 0.0 (`0.0 * 1.1` is still 0.0 against a strict `score > value` gate), so a
   `max` bar derived from 0.0 gets an absolute floor. A `min` bar at 0.0 needs none, because `0.0 < 0.0`
   is false. **It is a non-degeneracy floor, not a tolerance** — see item 6.
3. **Two tests added beyond the handoff's Test-first table**, both closing gate holes found in review,
   both recorded here against **AC4** so traceability checks do not read them as drift:
   `test_offline_mode_fails_when_a_metric_is_missing_from_the_thresholds_file` and
   `test_offline_mode_fails_when_a_threshold_bar_is_malformed_or_inverted`.
   A third, `test_build_generator_reports_a_config_failure_without_echoing_the_key`, pins the
   secret-redaction guard described in item 5.
4. **The thresholds file is a source of values, not of directions.** `direction_for(metric)` in
   `caption_eval.py` is the code-side authority. A bar whose `direction` disagrees with it, or is
   absent, or whose `value` is not a real number, is treated as *ungated* and fails the run by name.
   Before this, an absent bar — and then a malformed or direction-inverted one — let a metric pass
   silently while the harness printed "all metrics within their bars". A metric's direction is a
   property of the metric, not a tunable.
5. **Secret redaction on the config and auth error paths** (not in the handoff). A malformed
   `OPENAI_API_KEY` made pydantic render the raw value (`input_value=...`); both `build_generator()`
   and `run_nightly()` now raise `SystemExit` naming only the variable, with `from None` so the chain
   cannot print. Verified with a canary: zero occurrences in stdout or stderr.
6. **The bars are strict by construction, and the first nightly regen will very likely be red.**
   The snapshot pools 60 captions (20 analyses × 3 platforms), so the smallest nonzero score a `max`
   metric can report is 1/60 = 0.0167 (2/60 for opener/closer) — already above the 0.01 floor. The
   three zero-scoring metrics therefore have an effective tolerance of **zero**. That strictness is
   intended, but it is the concrete reason the spec's three-run-averaged re-baseline (Risks) should be
   the immediate fast-follow. Note this cannot redden ordinary code PRs: the offline job scores a
   *static committed* snapshot, so only a change to the metrics, fixtures or snapshot can move it.
7. **Cross-platform pooling in `score_snapshot`** — set-level metrics pool all three platforms into one
   60-caption set; the two per-caption metrics are averaged. The spec does not pin an aggregation.
   **PUB-051/PUB-052 should read `word_count_variance` with care**: pooled across platforms it partly
   measures telegram-vs-instagram length differences rather than within-platform diversity, so a change
   to the platform mix moves it for reasons unrelated to repetition. Per-platform pooling is the
   stronger design; it was not changed here because doing so would invalidate the snapshot/thresholds
   pair that AC4 verifies.
8. **`workflow_dispatch` on the nightly**, beyond the spec's literal "`schedule` trigger only". It is
   not `push`/`pull_request`, so the spec's actual intent — no OpenAI budget spend on PRs — holds.
9. **Nightly PRs are scored without a new credential.** PRs opened with `GITHUB_TOKEN` do not trigger
   workflow runs, so the `caption-eval` job would never have run on the one PR that changes
   `snapshot.json` — leaving the item's headline Success Metric unmet on exactly the branches it exists
   for. Rather than introduce a PAT or App token (a credentials decision that is the user's, not ours),
   a keyless `--offline` step scores the staged snapshot before the PR step. A regression now fails the
   nightly run itself and no PR is opened; `actions/upload-artifact` with `if: failure()` preserves the
   report and caption-level diff that explain why.
10. **Third-party actions are SHA-pinned**: `peter-evans/create-pull-request` at
    `c5a7806660adbe173f04e3e038b0ccdcd758773c` (v6.1.0) and `actions/upload-artifact` at
    `ea165f8d65b6e75b540449e92b4886f43607fa02` (v4.6.2), each independently re-resolved against the
    forge in review. `actions/checkout`, `setup-python` and `setup-uv` stay on tags per repo convention.
    The nightly checkout uses `persist-credentials: false`, and `permissions:` is scoped to the
    `regenerate` job rather than the workflow.
11. **Two collateral test updates** in `test_caption_sample_script.py` beyond the two AC7 tests:
    `test_a_failed_image_is_reported_not_dropped` and `test_pipe_characters_in_a_caption_do_not_break_the_table`
    hard-coded the table's column count, which AC7 widened from 7 to 8.
12. **Fixtures are synthesized, not historical.** `clone_set.json`'s six captions were *constructed* to
    the review's clone pattern (identical opener 3-gram, identical closer, 9.6% word-count spread) —
    the literal review captions are not stored anywhere retrievable. `snapshot.json` was generated
    offline through the real `_build_multi_prompt` with hand-authored captions; **no OpenAI call was
    made at any point**. The construction rules are documented in `fixtures/captions/README.md` and in
    a `construction` key inside the JSON itself.

## Post-review corrections (found on the PR, after the subagent rounds)

An independent review of the open PR found four defects that four earlier subagent review
rounds and a manual verification pass all missed. Recorded here because the misses are as
informative as the fixes:

13. **The nightly could never have run.** `load_application_config` hard-requires
    `STORAGE_PATHS`, `PUBLISHERS` and `OPENAI_SETTINGS`; the scheduled workflow supplies only
    `OPENAI_API_KEY`, so every run would have died at the first step. `caption_eval.py` now
    fills the same placeholders `scripts/caption_sample.py` already did, and reports which.
    *Why it was missed:* every prior check ran in this repo, where a local `.env` masks it.
14. **The secret redaction made that failure undiagnosable.** It withheld the real cause and
    named `OPENAI_API_KEY`, which was not the problem. `ConfigurationError` names missing
    variables and never quotes values, so it is surfaced; only the pydantic `ValidationError`,
    which renders `input_value=...`, stays withheld. Redaction that hides the diagnosis is not
    security.
15. **The prompt was not production's prompt.** `PlatformCaptionStyle.hashtags` is a bool flag;
    production resolves it as `hashtag_string if flag else ""`. Reading it as text rendered
    `Include hashtags: True.` into the prompt. `examples` and `smart_hashtags` were dropped
    too. All three now resolve as `CaptionSpec.for_platforms` resolves them, against documented
    fixture constants (`FIXTURE_HASHTAG_STRING`, no voice profile, smart hashtags off).
16. **The snapshot measured the pre-gate draft.** `_generate_snapshot` called the generator
    directly, skipping `AIService.create_multi_caption_pair_from_analysis` — the #82 similarity
    gate, the structure-directive rotation and the bounded regeneration. That systematically
    under-reports the mechanism PUB-051/PUB-052 exist to evaluate. The nightly seam is now
    `build_service()`. Cost: a tripped gate spends a second caption call for that image.

The committed `snapshot.json` and `caption_eval_thresholds.json` are unchanged throughout —
scoring never reads the specs — so the numbers above still stand.

## Follow-ups (not blockers for this item)

- Re-baseline `caption_eval_thresholds.json` over three nightly runs, per spec Risks — item 6 above is
  the concrete reason to do it early. Regenerating thresholds stays a deliberate, separate, human-invoked
  step: a nightly PR regenerates `snapshot.json` only and can never rewrite its own bar.
- Consider per-platform pooling for the set-level metrics (item 7) when PUB-051/PUB-052 start reading
  these numbers across items.
- The tells lexicon will need curation as real output accumulates; it is one list, one comment per pattern.
- Closing #146 and #138 with numbers from the first nightly run happens on those issues, and is not a
  pytest-gated AC of this item.
