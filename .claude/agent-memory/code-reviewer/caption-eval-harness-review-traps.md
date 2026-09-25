---
name: caption-eval-harness-review-traps
description: "PUB-049 caption eval harness traps — zero-bar epsilon buys no tolerance at n=60, GITHUB_TOKEN PRs skip the caption-eval check, thresholds silently skip missing metrics"
metadata:
  type: project
---

Traps found reviewing PUB-049 (caption evaluation harness, 2026-09-22):

- **A `max` bar of 0.01 on a share metric is zero tolerance, not a margin.** The committed
  snapshot pools **60 captions** (20 analyses x 3 platforms), so the smallest nonzero value of
  `tells_lexicon_hit_rate` / `two_sentence_emoji_rhythm_share` is 1/60 = 0.0167 and of
  `opener_closer_trigram_share` is 2/60 = 0.0333 — all above the `ZERO_BAR_EPSILON = 0.01` bar
  `--generate-thresholds` writes for a score of exactly 0.0. Any future "small absolute epsilon"
  margin must be checked against the metric's quantum (1/N), not just against zero.
- **`ZERO_BAR_EPSILON` was initially unpinned** — deleting the branch left the suite green (bars
  become 0.0, committed scores are 0.0, and `check_thresholds` uses strict `score > value`). Fixed:
  both directions are now pinned in `test_generate_thresholds_...` (max 0.0 -> 0.01, min 0.0 -> 0.0),
  proven by mutation. Same class as [[mutation-check-review-technique]].
- **`check_thresholds` used to do `if not bar: continue`** — a thresholds file that loses a metric
  stopped gating it silently. Fixed: it returns `(crossed, ungated)` and an ungated metric is its own
  exit-1 failure, pinned by `test_offline_mode_fails_when_a_metric_is_missing_from_the_thresholds_file`
  (a name outside the handoff table).
- **The nightly PR is opened with `secrets.GITHUB_TOKEN`**, and PRs created by `GITHUB_TOKEN` do
  not trigger workflows, so the `caption-eval` job in `code-quality.yml` never runs on the very PR
  that changes `snapshot.json`. Check this on any "bot opens a PR" workflow in this repo.
- `score_snapshot` pools all platforms for the set-level metrics, so `word_count_variance` is
  dominated by telegram-vs-instagram length differences, not by within-platform diversity. Read
  that number with care in PUB-051/PUB-052.
- The shared tokenizer landed as `words` / `word_ngrams` in `utils/captions.py` with
  `_words = words` kept as an alias (`test_caption_tokenizer_unicode.py` still imports `_words`).
  `ngram_set` was added but is dead code.
- `trigram_jaccard` deliberately survives (still used at `services/ai.py:1579`); PUB-052 decides
  its fate. Deleting it is out of scope.

**Why:** these are the non-obvious findings behind the PUB-049 review.
**How to apply:** on any diff touching `caption_eval.py`, `caption_metrics.py`, the caption
fixtures, or a scheduled workflow that opens PRs, check these first.
