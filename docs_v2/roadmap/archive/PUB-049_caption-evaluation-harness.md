# PUB-049: Caption Evaluation Harness

| Field | Value |
|-------|-------|
| **ID** | PUB-049 |
| **Category** | AI |
| **Priority** | P0 |
| **Effort** | M |
| **Status** | Done |
| **Dependencies** | — |

**Shipped date:** 2026-09-25
**Verified:** PR [#225](https://github.com/dhirmadi/SocialMediaPythonPublisher/pull/225), merge commit `431cbeb`; 1821 passed / 1 skipped, coverage 92.82% overall (`utils/caption_metrics.py` 93%); `ruff format --check` + `ruff check` clean; `mypy` clean (65 source files).

## User Story

As a publisher operator curating content, I want every change to the caption prompts, directives, sampling or history handling to come with a number that says whether captions got less repetitive and less machine-like, so that caption work stops being closed on green unit tests and reopened on the next batch of posts.

## Problem

Owner feedback: captions are repetitive and AI-like. Six prompt PRs merged on 19 and 20 September (#79, #81, #82, #131, #138, #147) and nobody can say whether any of them changed the output, because nothing measures it. The only diversity metric in the code is `utils/captions.py:302-316` `trigram_jaccard` with a 0.45 threshold (`services/ai.py:110`). Verified by execution: six hand-written captions any editor would call clones score a maximum pairwise 0.04; a 20-word sentence with three words swapped scores 0.31. The `caption_similarity` telemetry therefore reports diversity that does not exist. `scripts/caption_sample.py` (#146) measures only this metric and needs a live key. The unit test that proves the gate (`tests/test_caption_similarity.py:69-99`) feeds it a caption differing from history by one word. The "before/after on 20 images" criterion has been open since #79.

## Desired Outcome

An offline harness that runs in CI without a key in under ten seconds, scores a committed snapshot of generated captions on metrics that flag the repetition the owner sees, and fails when a change regresses them. A nightly mode with a key regenerates the snapshot and opens a PR with the diff and score table. Every later caption PR carries the before/after numbers in its body.

## Scope

**In scope:**
- Fixture under `publisher_v2/tests/fixtures/captions/`: 20 stored `ImageAnalysis` JSON files (fields only, no image bytes), the last 30 published captions per platform, and a constructed six-caption clone-set fixture (see AC1). The owner corpus is an optional, additive fixture source once available — its absence must not block any AC in this item
- `utils/caption_metrics.py`: opener and closer 3-gram share; sentence-count and word-count variance; share with the two-sentences-plus-emoji rhythm; tells-lexicon hit rate (extensible regex list); distinct-1 and distinct-2; TF-IDF bigram cosine to history; overlap of caption content words with the vision fields
- `scripts/caption_eval.py`: offline mode (render prompts through the real `_build_multi_prompt` as a rendering-regression smoke check, score the committed `snapshot.json` against `caption_eval_thresholds.json`) and nightly mode (regenerate `snapshot.json`, score it, write the diff/score table to disk)
- `caption_eval_thresholds.json`: checked-in thresholds, plus a `--generate-thresholds` mode that derives the file from a snapshot's scores (see AC6). Regenerating this file is always a separate, deliberate, human-invoked step — a nightly PR that regenerates `snapshot.json` never touches `caption_eval_thresholds.json` in the same PR, so ordinary run-to-run LLM variance in a merged snapshot cannot silently turn the next offline CI run red
- A new `caption-eval` job added to the existing `.github/workflows/code-quality.yml` (same `push`/`pull_request` triggers as the `lint`/`test` jobs already there), running offline mode and failing the build on a threshold regression — not a new workflow file, since this job shares the existing triggers and needs no new permissions
- A new, separate `.github/workflows/caption-eval-nightly.yml` on a `schedule` trigger only (never `push`/`pull_request`, since it spends an OpenAI budget and needs pull-request-open permissions) that runs `--nightly` and then opens the PR from the resulting branch using the runner's own token (`gh pr create` or `peter-evans/create-pull-request`) — the script itself never calls the GitHub API or holds a GitHub token
- Retirement of the trigram-only "Delta" column and "Mean similarity to the previous image" section in `scripts/caption_sample.py`, replaced by the harness's tells-rate/cosine deltas (see AC7)

**Out of scope:**
- Any change to prompts, directives, sampling or the gate (PUB-051, PUB-052)
- Human rubric tooling beyond a markdown table the owner fills in
- Deleting `trigram_jaccard` itself or the similarity gate in `services/ai.py` (PUB-052 decides its fate)

## Acceptance Criteria

- ✅ AC1: Given `publisher_v2/tests/fixtures/captions/clone_set.json` — six captions constructed (and documented in-file as constructed, since the literal review captions are not stored anywhere retrievable) to match the review's clone pattern: identical opener words, an identical one-line closer, and under 15% word-count variance across the six — when they are scored pairwise, then TF-IDF bigram cosine and tells-lexicon hit rate both cross their `caption_eval_thresholds.json` bar and `trigram_jaccard` on the same pairs stays at or below the 0.04 ceiling measured in the Problem section; the gap is asserted by one test (e.g. `test_clone_set_flagged_by_new_metrics_not_by_trigram`). *Verified: tells rate 1.00 vs bar 0.01; worst pairwise TF-IDF cosine 0.0544 vs bar 0.0108; worst pairwise `trigram_jaccard` 0.0323, under the 0.04 ceiling.*
- ✅ AC2: Given a small hand-computed input for each of the seven `caption_metrics` functions (opener/closer 3-gram share, sentence-count/word-count variance, two-sentence-plus-emoji rhythm share, tells-lexicon hit rate, distinct-1/distinct-2, TF-IDF bigram cosine to history, vision-field content-word overlap), when each metric runs on its own input, then it returns the exact value computed by hand, one test per metric. *Verified: seven separate tests, five independently re-derived in review.*
- ✅ AC3: Given no `OPENAI_API_KEY` and the OpenAI client patched to raise if called, when `scripts/caption_eval.py --offline` runs, then it makes zero network calls, completes in under ten seconds, and prints a score table for the committed `snapshot.json`; a separate check in the same run re-renders every fixture's prompt through the real `_build_multi_prompt` and fails loudly on any exception, without that render itself being scored as a metric. *Verified: 0.31s wall clock; zero network calls confirmed with sockets patched to raise.*
- ✅ AC4: Given `caption_eval_thresholds.json` in the schema `{"<metric_name>": {"direction": "max"|"min", "value": <float>}}` (one entry per metric; `direction` states which side is a regression), when the offline mode scores the snapshot and any metric crosses its `value` on the regression `direction`, then the process exits non-zero, names the offending metric(s) in its output, and CI fails on that exit code. *Verified, plus two review-added tests closing an ungated-metric hole (see summary Deviations #3–4).*
- ✅ AC5: Given a key and a budget, when `scripts/caption_eval.py --nightly` runs, then it regenerates `snapshot.json` for the 20 fixture analyses and writes the diff and score table to disk for the calling workflow to open as a PR (the script does not call the GitHub API itself; see Scope). *Verified; nightly workflow additionally scores keylessly before opening a PR, per summary Deviation #9.*
- ✅ AC6: Given a snapshot's score table, when `scripts/caption_eval.py --generate-thresholds` runs (backed by a pure function, e.g. `generate_thresholds(scores: dict[str, float]) -> dict`, unit-testable with a fixed input), then it writes `caption_eval_thresholds.json` with each metric's bar set from that table plus a documented margin so a same-quality re-run does not immediately fail; this first-run file is committed alongside the harness, and Risks records that a three-run-averaged bar is a fast-follow, not a blocker, for this item. *Verified byte-identical on regeneration (md5 `44c3f13f477e627ab781a04a7d4c2b35`).*
- ✅ AC7: Given `scripts/caption_sample.py`'s Markdown output, when the trigram-only "Delta" column and "Mean similarity to the previous image" section are replaced with the harness's tells-rate and TF-IDF-cosine deltas, then `test_the_table_pairs_each_platform_and_scores_similarity` and `test_similarity_to_the_previous_image_is_reported_per_variant` in `publisher_v2/tests/test_caption_sample_script.py` are updated to assert on the new columns and pass. *Verified: the word "trigram" no longer appears in the rendered Markdown; `trigram_jaccard` itself untouched (PUB-052's call).*

## Implementation Notes

- Metrics are pure Python; no new runtime dependency. TF-IDF over bigrams can be implemented in fifty lines; do not add scikit-learn.
- The prompt-render half exercises the real builder so a prompt change that breaks rendering fails here too.
- `caption_eval_thresholds.json` schema (AC4/AC6): `{"<metric_name>": {"direction": "max"|"min", "value": <float>}}`. `direction: "max"` means the run fails if the metric's score rises above `value` (e.g. TF-IDF cosine, tells rate); `direction: "min"` means it fails if the score falls below `value` (e.g. distinct-1/distinct-2). `--generate-thresholds` applies a fixed margin (suggest ±10%, in the direction that makes the just-generated snapshot pass) so the bootstrap run is not immediately red.
- `sentence_word_count_variance` uses **population** variance (divide by N, not N-1) — pin this now rather than leaving it to the implementer, since PUB-051/PUB-052 read these numbers across items and a later inconsistency would be a quiet semantics drift.
- Word-level tokenization and n-gram construction (opener/closer 3-grams, distinct-n) must reuse a single shared helper with the existing `trigram_jaccard`/`_words` logic in `utils/captions.py` — promote `_words` (and the n-gram-set construction) to a public, shared function there (or a tiny shared module) rather than hand-copying it into `caption_metrics.py`. Two independently-maintained caption tokenizers is exactly the drift DRY exists to prevent.
- Coverage: `utils/caption_metrics.py` is inside `[tool.coverage.run] source` (`pyproject.toml`) and is subject to the ≥80%-affected / ≥85%-overall gates. `scripts/caption_eval.py` (like today's `scripts/caption_sample.py`) is **outside** that `source` path and is not measured by `--cov-fail-under=85` at all — write tests for it for correctness, but do not claim it against the coverage gate.
- This item's job is done once the harness exists and prints real numbers; closing #146 and #138 with those numbers (Success Metrics) happens on the issues themselves after the first nightly run, and is not itself a pytest-gated AC.
- Sub-issue #189. Blocks every other Phase 2 sub-issue on #177 (working rule 2).
- Budget and the trial model come from #182.

## Risks

- A snapshot generated once by a nightly run is a point sample; thresholds should allow some variance (set from three nightly runs where budget permits). Because `--generate-thresholds` is always a separate, deliberate step from a nightly regen (see Scope), ordinary run-to-run variance in a merged snapshot cannot silently turn CI red on its own — but it means the very first `caption_eval_thresholds.json` is looser than ideal until re-baselined.
- The tells lexicon will need curation; keep it in one file with a comment per pattern.
- `clone_set.json` (AC1) validates one constructed clone shape — shared opener, shared closer, low word-count variance. It does not cover the full space of "machine-like" repetition a human reviewer might flag; the nightly snapshot plus the owner's markdown-table read (Scope, out of scope: human rubric) remains the real backstop for anything outside that shape.
- The committed `snapshot.json` and `caption_eval_thresholds.json` must agree the moment they land (AC4's end-to-end test, see handoff) — a mismatch here would make CI red from day one, not from a real regression.

## Success Metrics

- CI fails on a branch whose snapshot regresses any metric past its checked-in `caption_eval_thresholds.json` bar.
- #146 and #138 closed with numbers from the harness (see Implementation Notes).

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issue [#189](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/189); absorbs [#146](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/146)
- [PUB-035: Caption Context Intelligence](archive/PUB-035_caption-context-intelligence.md) — introduced the history window this measures against
- `docs_v2/07_AI/AI_PROMPTS_AND_MODELS.md` §6 ("keep a small golden set"), which this finally implements

## Change Log

- 2026-09-22 — Spec hardened for Claude Code handoff (`/product-harden`). Independent architect review ran; all four Must-fix findings applied (Success Metrics copy/paste error corrected; unenforceable `scripts/` coverage claim fixed; real-artifact end-to-end smoke test added to AC4; CI topology for the offline job vs. nightly workflow committed instead of left open). Should-improve findings applied (nightly-vs-thresholds lifecycle separation stated explicitly; shared tokenizer/n-gram helper called out instead of duplication; AC5 split into two tests). Nice-to-haves applied (clone-set scope limit noted in Risks; population-variance convention pinned).
