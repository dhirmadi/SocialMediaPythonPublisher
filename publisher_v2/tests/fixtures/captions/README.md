# Caption evaluation fixtures (PUB-049)

Everything in this directory is **synthetic test data written for the caption
evaluation harness**, except `snapshot.json` and `baseline_runs/` (see below).
None of the synthetic files is production output, and none of it is the literal
text from the owner's caption review — that text is not stored anywhere
retrievable. Do not cite them as evidence of what the model actually produced on
any date.

## `clone_set.json` (AC1)

Six captions **constructed** to reproduce the clone shape the owner flagged.
The construction rule, verbatim:

1. **Identical opener** — every caption starts with the same three words,
   `There is something`.
2. **Identical closer** — every caption ends with the same one-line closing
   sentence, `Stay a while.`
3. **Low word-count spread** — the six captions run 50–55 words, a spread of
   9.6% of the mean, i.e. under the 15% bar AC1 asks for.
4. **Disjoint middles** — the body of each caption uses deliberately different
   vocabulary, so that word-trigram overlap stays at the floor forced by rules
   1 and 2 (three shared trigrams per pair: `there is something`,
   `is something about`, `stay a while`).
5. **One tell per caption** — each caption carries at least one stock
   AI-caption phrase, so the tells lexicon has something to find. The phrases
   used are: the shared `there is something about` opener, plus `isn't just`,
   `in a world where`, `a testament to`, `let's be honest`, and `whether
   you're`. The default lexicon in `utils/caption_metrics.py` must cover these,
   or AC1's test fails.

Why this matters: rules 1–4 together are exactly the case
`trigram_jaccard` cannot see. Measured with the existing implementation, the
**maximum pairwise `trigram_jaccard` across all fifteen pairs is 0.0323** —
under the 0.04 ceiling the spec's Problem section records — while any editor
would call these six captions clones. That gap is what AC1 asserts.

## `analyses/*.json` (AC2, AC3, AC5)

Twenty `ImageAnalysis` field dumps (fields only, no image bytes), matching the
dataclass in `publisher_v2/src/publisher_v2/core/models.py`. `description`,
`tags` and `mood` are varied on purpose so the snapshot generated from them is
not itself a clone set.

## `history/*.json` (AC2, AC3, AC5)

One file per platform, each holding the "last 30 published captions" the
harness scores a new caption against. Synthesised from a varied pool of
sentences; not production history.

## `snapshot.json`, `baseline_runs/` and `caption_eval_thresholds.json`

**Live model output, not hand-written fixtures** (PUB-080). The PUB-049
bootstrap snapshot was synthetic; it was replaced on 2026-09-27, then widened
from five to ten runs on 2026-10-13 (see below).

- `baseline_runs/run1.json` … `run5.json`: five `--nightly` runs of the Caption
  Eval Nightly workflow on `main` at `4e146ad`, caption model `gpt-4o-mini`,
  2026-09-27 (Actions runs 36321465445, 36321644178, 36321719207, 36321802429,
  36321879634). They are the evidence PUB-080's bars were derived from.
- `baseline_runs/run6.json` … `run10.json`: five more `scripts/caption_eval.py
  --nightly` runs, same caption model `gpt-4o-mini`, run locally (not via
  Actions — equivalent output, same code path) on `main` at `74ac9fe`,
  2026-10-13. Added because the nightly was failing its own scoring step on
  about 60% of nights (9 of the last 15 as of 2026-10-13), always on a
  different metric, consistent with PUB-080's own "Risks" section predicting
  that five runs might not cover the full range and naming "add runs to
  `baseline_runs/` and regenerate; do not widen the margin" as the fix.
- `snapshot.json`: a copy of `run10.json`, the latest baseline run. The nightly
  workflow's PRs replace it with later output; the baseline runs stay put.
- `caption_eval_thresholds.json`: derived from **all ten** baseline runs. Each
  bar is the worst score across the runs (highest for a "max" metric, lowest
  for a "min" metric) with the PUB-049 10% margin, so every baseline run
  passes. Identical runs vary far more than 10% (opener share 0.07–0.30; see
  PUB-080), which is why the bars do not come from one run or from the mean.

To re-baseline (a deliberate, reviewed step; the nightly never does this):
download new `caption-eval-report` artifacts into `baseline_runs/`, then run

```bash
PYTHONPATH=publisher_v2/src uv run python scripts/caption_eval.py --generate-thresholds \
  $(for f in publisher_v2/tests/fixtures/captions/baseline_runs/run*.json; do printf -- '--snapshot %s ' "$f"; done) \
  --out publisher_v2/tests/fixtures/captions/caption_eval_thresholds.json
```

`test_committed_thresholds_admit_every_recorded_baseline_run` fails if any
recorded run crosses the committed bars.
