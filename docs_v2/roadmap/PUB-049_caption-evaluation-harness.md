# PUB-049: Caption Evaluation Harness

| Field | Value |
|-------|-------|
| **ID** | PUB-049 |
| **Category** | AI |
| **Priority** | P0 |
| **Effort** | M |
| **Status** | Proposal |
| **Dependencies** | — |

## User Story

As a publisher operator curating content, I want every change to the caption prompts, directives, sampling or history handling to come with a number that says whether captions got less repetitive and less machine-like, so that caption work stops being closed on green unit tests and reopened on the next batch of posts.

## Problem

Owner feedback: captions are repetitive and AI-like. Six prompt PRs merged on 19 and 20 September (#79, #81, #82, #131, #138, #147) and nobody can say whether any of them changed the output, because nothing measures it. The only diversity metric in the code is `utils/captions.py:302-316` `trigram_jaccard` with a 0.45 threshold (`services/ai.py:110`). Verified by execution: six hand-written captions any editor would call clones score a maximum pairwise 0.04; a 20-word sentence with three words swapped scores 0.31. The `caption_similarity` telemetry therefore reports diversity that does not exist. `scripts/caption_sample.py` (#146) measures only this metric and needs a live key. The unit test that proves the gate (`tests/test_caption_similarity.py:69-99`) feeds it a caption differing from history by one word. The "before/after on 20 images" criterion has been open since #79.

## Desired Outcome

An offline harness that runs in CI without a key in under ten seconds, scores a committed snapshot of generated captions on metrics that flag the repetition the owner sees, and fails when a change regresses them. A nightly mode with a key regenerates the snapshot and opens a PR with the diff and score table. Every later caption PR carries the before/after numbers in its body.

## Scope

**In scope:**
- Fixture under `publisher_v2/tests/fixtures/captions/`: 20 stored `ImageAnalysis` JSON files (fields only, no image bytes), the last 30 published captions per platform, the owner corpus once available
- `utils/caption_metrics.py`: opener and closer 3-gram share; sentence-count and word-count variance; share with the two-sentences-plus-emoji rhythm; tells-lexicon hit rate (extensible regex list); distinct-1 and distinct-2; TF-IDF bigram cosine to history; overlap of caption content words with the vision fields
- `scripts/caption_eval.py`: offline mode (render prompts through the real `_build_multi_prompt`, score the snapshot) and nightly mode (regenerate, score, open a PR)
- CI job running offline mode with thresholds in a checked-in `caption_eval_thresholds.json`
- Retirement of the trigram-only parts of `scripts/caption_sample.py`

**Out of scope:**
- Any change to prompts, directives, sampling or the gate (PUB-051, PUB-052)
- Human rubric tooling beyond a markdown table the owner fills in

## Acceptance Criteria

- AC1: Given the six-caption clone set from the review, when it is scored, then TF-IDF bigram cosine and tells rate both flag it and trigram Jaccard does not (the gap is documented by a test)
- AC2: Given each metric and a tiny hand-computed set, when the metric runs, then it returns the expected value
- AC3: Given no `OPENAI_API_KEY`, when `scripts/caption_eval.py --offline` runs, then it completes in under ten seconds and prints a score table for the committed snapshot
- AC4: Given a metric crosses its threshold in `caption_eval_thresholds.json`, when the offline mode runs, then the exit code is non-zero and CI fails
- AC5: Given a key and a budget, when the nightly mode runs, then it regenerates `snapshot.json` for the 20 analyses and opens a PR containing the diff and the score table
- AC6: Given the first snapshot on `main`, when the thresholds file is generated, then the bar is set from that snapshot and committed
- AC7: Given the harness lands, when #146 is checked, then its 20-image evidence comes from the first nightly run and #138 receives the same table for the owner's reading

## Implementation Notes

- Metrics are pure Python; no new runtime dependency. TF-IDF over bigrams can be implemented in fifty lines; do not add scikit-learn.
- The prompt-render half exercises the real builder so a prompt change that breaks rendering fails here too.
- Sub-issue #189. Blocks every other Phase 2 sub-issue on #177 (working rule 2).
- Budget and the trial model come from #182.

## Risks

- A snapshot generated once by a nightly run is a point sample; thresholds should allow some variance (set from three nightly runs where budget permits).
- The tells lexicon will need curation; keep it in one file with a comment per pattern.

## Success Metrics

- CI fails on a branch that reintroduces the closing-question mandate or the static email examples.
- #146 and #138 closed with numbers.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issue [#189](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/189); absorbs [#146](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/146)
- [PUB-035: Caption Context Intelligence](archive/PUB-035_caption-context-intelligence.md) — introduced the history window this measures against
- `docs_v2/07_AI/AI_PROMPTS_AND_MODELS.md` §6 ("keep a small golden set"), which this finally implements
