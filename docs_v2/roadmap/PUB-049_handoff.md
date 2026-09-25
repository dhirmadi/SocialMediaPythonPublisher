# Implementation Handoff: PUB-049 — Caption Evaluation Harness

**Hardened:** 2026-09-22
**Status:** Ready for implementation

## For Claude Code

### Test-first targets

| AC | Test file | Test name (exact function) |
|----|-----------|-----------------------------|
| AC1 | `publisher_v2/tests/test_caption_metrics.py` | `test_clone_set_flagged_by_new_metrics_not_by_trigram` |
| AC2 | `publisher_v2/tests/test_caption_metrics.py` | `test_opener_closer_trigram_share_matches_hand_computed_value` |
| AC2 | `publisher_v2/tests/test_caption_metrics.py` | `test_sentence_and_word_count_variance_matches_hand_computed_value` |
| AC2 | `publisher_v2/tests/test_caption_metrics.py` | `test_two_sentence_emoji_rhythm_share_matches_hand_computed_value` |
| AC2 | `publisher_v2/tests/test_caption_metrics.py` | `test_tells_lexicon_hit_rate_matches_hand_computed_value` |
| AC2 | `publisher_v2/tests/test_caption_metrics.py` | `test_distinct_1_and_distinct_2_match_hand_computed_value` |
| AC2 | `publisher_v2/tests/test_caption_metrics.py` | `test_tfidf_bigram_cosine_to_history_matches_hand_computed_value` |
| AC2 | `publisher_v2/tests/test_caption_metrics.py` | `test_vision_field_content_word_overlap_matches_hand_computed_value` |
| AC3 | `publisher_v2/tests/test_caption_eval_script.py` | `test_offline_mode_makes_zero_network_calls_and_completes_under_ten_seconds` |
| AC3 | `publisher_v2/tests/test_caption_eval_script.py` | `test_offline_mode_fails_loudly_when_prompt_rendering_raises` |
| AC4 | `publisher_v2/tests/test_caption_eval_script.py` | `test_offline_mode_exits_nonzero_and_names_metric_on_threshold_regression` |
| AC4 | `publisher_v2/tests/test_caption_eval_script.py` | `test_offline_mode_passes_cleanly_on_the_real_committed_snapshot_and_thresholds` |
| AC5 | `publisher_v2/tests/test_caption_eval_script.py` | `test_nightly_mode_regenerates_snapshot_and_writes_diff_to_disk` |
| AC5 | `publisher_v2/tests/test_caption_eval_script.py` | `test_nightly_mode_never_imports_or_calls_anything_github_shaped` |
| AC6 | `publisher_v2/tests/test_caption_eval_script.py` | `test_generate_thresholds_derives_bar_from_snapshot_scores_with_margin` |
| AC7 | `publisher_v2/tests/test_caption_sample_script.py` | `test_the_table_pairs_each_platform_and_scores_similarity` (updated) |
| AC7 | `publisher_v2/tests/test_caption_sample_script.py` | `test_similarity_to_the_previous_image_is_reported_per_variant` (updated) |

The **Test name** column is the exact `pytest` function name Claude Code must create — the
only spec-to-test traceability link this contract relies on. AC2 spans seven tests, one per
metric function in `utils/caption_metrics.py`; do not collapse them into one parametrized
test without recording the deviation in the summary doc (traceability checks want the literal
names above). AC4 and AC5 each now span two tests — a behavioral one and a structural/
boundary one — for the same reason: keep failure signals separable. If a different name is
genuinely clearer, record the actual name used in `PUB-049_summary.md` next to the AC it
satisfies.

### Metric functions to implement (`utils/caption_metrics.py`)

Suggested function names (adjust and record any deviation in the summary doc):

| Function | Returns | Notes |
|----------|---------|-------|
| `opener_closer_trigram_share(captions: list[str]) -> float` | share of captions sharing an opener/closer 3-gram with another caption in the set | reuse the shared word-tokenizer/n-gram helper (see below) — do not hand-copy `_words` |
| `sentence_word_count_variance(captions: list[str]) -> dict[str, float]` | `{"sentence_count_variance": ..., "word_count_variance": ...}` | **population** variance (divide by N, not N-1) — pinned in the spec's Implementation Notes, do not pick a different convention |
| `two_sentence_emoji_rhythm_share(captions: list[str]) -> float` | fraction of captions matching "exactly two sentences + trailing emoji" | regex-based sentence split is fine; keep it simple |
| `tells_lexicon_hit_rate(captions: list[str], lexicon: list[str] | None = None) -> float` | fraction of captions matching ≥1 lexicon pattern | default lexicon lives in this module, one regex per line with a comment (see Risks in the spec); must be trivially extensible |
| `distinct_n(captions: list[str], n: int) -> float` | distinct-n ratio (unique n-grams / total n-grams) across the caption set | `n=1` and `n=2` both needed; single function, called twice |
| `tfidf_bigram_cosine(caption: str, history: list[str]) -> float` | cosine similarity of the caption's bigram TF-IDF vector against the history corpus | hand-rolled TF-IDF over bigrams, no scikit-learn (spec Implementation Notes) |
| `vision_field_overlap(caption: str, analysis: ImageAnalysis) -> float` | share of caption content words also present in the analysis's text fields (`description`, `tags`, `distinctive_detail`, etc.) | reuse `ImageAnalysis` from `core/models.py`; only import public fields |

**Shared tokenizer (DRY, per the architect review):** promote `_words` in
`utils/captions.py` to a public function (e.g. rename to `words()` or export
`words = _words` with a comment) and reuse it — and the n-gram-set construction
`trigram_jaccard` already does — from `caption_metrics.py` instead of duplicating either.
This keeps exactly one definition of "how a caption tokenizes into words/n-grams" in the
codebase. If `captions.py` and `caption_metrics.py` end up needing more shared surface than
just this, that's a signal to extract a small `utils/caption_text.py`, but do not do that
speculatively — start with exporting the one function.

### Fixture construction (AC1, AC2, AC3)

- `publisher_v2/tests/fixtures/captions/clone_set.json`: six captions **constructed for this
  harness**, not literally sourced from the review thread (that text is not stored anywhere
  retrievable — see spec AC1 note). Construct them to share: (a) identical first three words,
  (b) an identical closing sentence, (c) under 15% word-count variance across the six. Document
  the construction rule in a comment at the top of the JSON file (or a sibling `.md`/README next
  to it) so a future reader does not mistake it for real historical data.
- `publisher_v2/tests/fixtures/captions/analyses/*.json`: 20 `ImageAnalysis` field dumps (no
  image bytes) — synthesize plausible values across the dataclass's fields (`core/models.py`);
  vary `description`/`tags`/`mood` enough that the snapshot isn't itself a clone set.
- `publisher_v2/tests/fixtures/captions/history/*.json`: last 30 published captions per
  platform — synthesize a small, varied set (10–20 sentences is enough to cycle through for 30
  slots); does not need to be real production data.
- `publisher_v2/tests/fixtures/captions/snapshot.json`: the committed "current" scored output —
  generate once (by hand or by a throwaway script run) from the above fixtures through
  `_build_multi_prompt` + a stubbed/fixed set of captions, since generating it via a live OpenAI
  call is exactly what offline mode must avoid depending on. This file is committed and is what
  AC3/AC4's offline scoring reads. Generate `caption_eval_thresholds.json` from this exact
  `snapshot.json` (via `--generate-thresholds`) so the two land together and the real-artifact
  smoke test (`test_offline_mode_passes_cleanly_on_the_real_committed_snapshot_and_thresholds`)
  passes on the first commit — do not hand-write the thresholds file separately from the
  snapshot it's supposed to score.
- Owner corpus (mentioned in scope) is optional and not required to satisfy any AC in this
  item — do not block on its absence.

### Mock boundaries

| External service | Mock strategy | Existing fixture/pattern |
|-------------------|---------------|---------------------------|
| OpenAI (offline mode) | Patch the OpenAI client (or whatever `scripts/caption_eval.py` imports) to raise `AssertionError` on any call attempt, proving AC3's "zero network calls" | Follow the `unittest.mock.patch` style already used in `publisher_v2/tests/test_ai_*.py` |
| OpenAI (nightly mode) | `unittest.mock.patch` returning canned `AIUsage`/caption responses, matching `AIService` test doubles in `test_ai_multi_caption.py` | `tests/conftest.py` if a shared fixture already exists there; otherwise a local fake generator like `_GateStubGenerator` in `test_caption_similarity.py` |
| GitHub API (PR creation) | Not mocked in Python tests at all — AC5's test asserts the script writes files to disk and never imports/calls anything network-shaped for GitHub; PR creation is a GitHub Actions workflow step (`gh pr create` / `peter-evans/create-pull-request`), out of Python-test scope entirely |
| Filesystem (`snapshot.json`, thresholds file) | Use `tmp_path` fixtures; never let a test write into the real committed fixture files | Standard pytest `tmp_path` |

### Files likely touched

| Area | Files to modify | Files to create |
|------|------------------|-------------------|
| Metrics | — | `publisher_v2/src/publisher_v2/utils/caption_metrics.py`, `publisher_v2/tests/test_caption_metrics.py` |
| Eval script | — | `scripts/caption_eval.py`, `publisher_v2/tests/test_caption_eval_script.py` |
| Fixtures | — | `publisher_v2/tests/fixtures/captions/clone_set.json`, `.../analyses/*.json`, `.../history/*.json`, `.../snapshot.json` |
| Thresholds | — | `caption_eval_thresholds.json` (repo root or alongside the fixtures — Claude Code's call; state the choice in the summary doc) |
| CI | `.github/workflows/code-quality.yml` (add a new `caption-eval` job, same `push`/`pull_request` triggers as `lint`/`test`) | `.github/workflows/caption-eval-nightly.yml` (new file, `schedule` trigger only — never `push`/`pull_request`, per spec Scope) |
| Sample script retirement | `scripts/caption_sample.py`, `publisher_v2/tests/test_caption_sample_script.py` | — |

### Non-negotiables for this item

- [ ] Preview mode: N/A — this item touches CLI/CI scripts only, not the publish pipeline; still, `--offline` must never make any network call (AC3) and must never touch Dropbox, publisher, or state/cache — it only reads fixture files.
- [ ] Secrets: `--nightly` reads `OPENAI_API_KEY` the same way other scripts do (never logged, never hard-coded); the eval script must never hold or use a GitHub token — PR creation is the workflow's job, not the script's (AC5).
- [ ] Auth: N/A (no web endpoint changes).
- [ ] Async hygiene: `_build_multi_prompt` is synchronous already — no `asyncio.to_thread` needed for the render half; if `--nightly` calls the real `AIService`/`AIClient` async methods, run them via `asyncio.run` at the script's top level like other CLI scripts do, not by mixing sync/async carelessly.
- [ ] Coverage: ≥80% on `utils/caption_metrics.py` (it is inside `[tool.coverage.run] source` in `pyproject.toml`). `scripts/caption_eval.py` is **outside** that source path, like `scripts/caption_sample.py` today, and is not measured by `--cov-fail-under=85` — write tests for correctness, but do not claim it against the coverage gate. ≥85% overall maintained regardless.
- [ ] No new runtime dependency (spec Implementation Notes) — hand-rolled TF-IDF, no scikit-learn.

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-049_caption-evaluation-harness.md
```
