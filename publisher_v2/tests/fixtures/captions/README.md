# Caption evaluation fixtures (PUB-049)

Everything in this directory is **synthetic test data written for the caption
evaluation harness**. None of it is production output, and none of it is the
literal text from the owner's caption review — that text is not stored anywhere
retrievable. Do not cite these files as evidence of what the model actually
produced on any date.

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

## `snapshot.json` and `caption_eval_thresholds.json`

**Generated artifacts, not hand-written fixtures.** `snapshot.json` is produced
by `scripts/caption_eval.py --nightly` (or a one-off bootstrap run) and
`caption_eval_thresholds.json` is derived from it by
`scripts/caption_eval.py --generate-thresholds`. They must always be generated
as a pair from the same snapshot, or offline CI is red on arrival (spec Risks).
