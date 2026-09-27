# PUB-080: Re-baseline the Caption Eval From Live Output

| Field | Value |
|-------|-------|
| **ID** | PUB-080 |
| **Category** | AI |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Done |
| **Dependencies** | PUB-049, PUB-051 |
| **Shipped date** | 2026-09-27 |
| **Verified** | PR [#266](https://github.com/dhirmadi/SocialMediaPythonPublisher/pull/266), merge commit `2e20538` |

## User Story

As the owner, I want the caption-eval bars to come from real model output, so that the nightly run
goes red only when captions actually get worse, not every night by construction.

## Problem

Tracked in [#234](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/234).

1. **The committed baseline is synthetic.** `publisher_v2/tests/fixtures/captions/snapshot.json` is
   PUB-049's hand-shaped bootstrap, and `caption_eval_thresholds.json` was derived from it. Real
   output cannot meet those bars.
2. **The nightly now runs, and fails every time.** `OPENAI_API_KEY` was set on 2026-09-27. Five
   `workflow_dispatch` runs of Caption Eval Nightly on `main` at `4e146ad` (runs 36321465445,
   36321644178, 36321719207, 36321802429, 36321879634) all failed at "Score the regenerated
   snapshot".
3. **Run-to-run noise is far wider than the ±10% margin.** Across those five identical runs:

   | Metric | Dir | r1 | r2 | r3 | r4 | r5 | Mean | Worst |
   |---|---|---|---|---|---|---|---|---|
   | opener_closer_trigram_share | max | 0.0833 | 0.2000 | 0.3000 | 0.1000 | 0.0667 | 0.1500 | 0.3000 |
   | two_sentence_emoji_rhythm_share | max | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
   | tells_lexicon_hit_rate | max | 0.0333 | 0 | 0.0167 | 0 | 0.0667 | 0.0233 | 0.0667 |
   | tfidf_bigram_cosine | max | 0.0039 | 0.0045 | 0.0038 | 0.0046 | 0.0034 | 0.0040 | 0.0046 |
   | vision_field_overlap | max | 0.1267 | 0.1459 | 0.1417 | 0.1232 | 0.1238 | 0.1323 | 0.1459 |
   | sentence_count_variance | min | 0.3989 | 0.4097 | 0.4322 | 0.5056 | 0.5164 | 0.4526 | 0.3989 |
   | word_count_variance | min | 13.714 | 14.366 | 17.228 | 15.700 | 14.390 | 15.079 | 13.714 |
   | distinct_1 | min | 0.3339 | 0.3297 | 0.3178 | 0.3177 | 0.3382 | 0.3275 | 0.3177 |
   | distinct_2 | min | 0.7980 | 0.8060 | 0.8060 | 0.7922 | 0.8112 | 0.8027 | 0.7922 |

   Bars at mean ±10%, as #234 first proposed, would have failed all five of these runs (r1
   sentence_count and tells; r2 opener, tfidf and vision; r3 opener; r4 tfidf; r5 tells). A gate
   that is red every night is not a regression signal.

## Decision (owner, 2026-09-27)

Bars are the **worst score across the baseline runs, with the existing ±10% margin**: the highest
value for a `max` metric, the lowest for a `min` metric, then `generate_thresholds` unchanged. Every
baseline run passes by construction, so a red nightly means output left its observed range. This
replaces #234's "mean of 3–5 runs" wording. The margin, the metrics and the zero-bar floor are
unchanged (PUB-049 policy).

## Scope

**In scope:**
- `scripts/caption_eval.py --generate-thresholds` accepts `--snapshot` more than once and derives the
  bars from the worst score per metric across all of them. With one snapshot the output is
  identical to today.
- `--offline` rejects more than one `--snapshot`.
- Commit the five live runs as `publisher_v2/tests/fixtures/captions/baseline_runs/run{1..5}.json`, so
  the bars are reproducible from the repo.
- Replace `snapshot.json` with run 5 (the latest) and regenerate `caption_eval_thresholds.json` from all
  five runs.
- Update `publisher_v2/tests/fixtures/captions/README.md`: the snapshot and baseline runs are live
  `gpt-4o-mini` output from 2026-09-27, `main` at `4e146ad`; how to re-baseline.

**Out of scope:**
- Changing the metrics, the margin or the zero-bar floor (PUB-049).
- A voice profile in the fixtures (PUB-064).
- Making the nightly regenerate thresholds; re-baselining stays human-invoked.

## Acceptance Criteria

- AC1: Given several score tables, when the worst scores are taken, then each `max` metric gets the
  highest value and each `min` metric the lowest.
- AC2: Given `--generate-thresholds` with two or more `--snapshot` arguments, when it runs, then the
  bars derive from the worst score per metric, and `--offline` against each of those snapshots with
  the written bars exits 0.
- AC3: Given `--offline` with more than one `--snapshot`, when it runs, then it exits with an error
  naming the flag and scores nothing.
- AC4: Given the committed thresholds, when each committed baseline run is scored offline, then every
  run passes.
- AC5: Given the committed `snapshot.json` and thresholds, when `--offline` runs with defaults, then
  it exits 0 (existing test).
- AC6: Given this item ships, when a `workflow_dispatch` run of Caption Eval Nightly runs on `main`,
  then it completes green through "Score the regenerated snapshot". This is a human-run check after
  merge, not a pytest.

## Test-first targets

| AC | Test |
|----|------|
| AC1 | `publisher_v2/tests/test_caption_eval_script.py::test_worst_scores_takes_the_worst_value_per_metric_direction` |
| AC2 | `publisher_v2/tests/test_caption_eval_script.py::test_generate_thresholds_from_several_snapshots_lets_every_run_pass` |
| AC3 | `publisher_v2/tests/test_caption_eval_script.py::test_offline_mode_rejects_more_than_one_snapshot` |
| AC4 | `publisher_v2/tests/test_caption_eval_script.py::test_committed_thresholds_admit_every_recorded_baseline_run` |
| AC5 | `publisher_v2/tests/test_caption_eval_script.py::test_offline_mode_passes_cleanly_on_the_real_committed_snapshot_and_thresholds` |

## Risks

- **Five runs may not cover the full range.** A sixth run can still land outside it, and a red night
  may then be noise. If that happens more than rarely, add runs to `baseline_runs/` and regenerate;
  do not widen the margin.
- **Worst-of-N only loosens as runs are added.** Bars are reviewed in the PR that adds runs, like any
  other threshold change.

## References

- [#234](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/234) — this item's issue
- PUB-049 (archive) — harness, metrics, margin policy
- PUB-051 summary (archive) — earlier live 5-run means
