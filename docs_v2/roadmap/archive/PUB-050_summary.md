# PUB-050 — Owner Voice Corpus in Every Caption Prompt: Implementation Summary

**Status:** Done — merged to main in #226
**Date:** 2026-09-25 – 2026-09-26

## Files Changed

### Production
- `publisher_v2/src/publisher_v2/services/ai.py` — new pure `sample_voice_examples(examples, seed_source, platform_tags=None, platforms=None, target_min=4, target_max=6, max_tokens_budget=DEFAULT_VOICE_PROFILE_TOKEN_BUDGET)`, implementing the roadmap's pinned algorithm verbatim: dedup via `dict.fromkeys` → partition `preferred`/`rest` in **pool** order → `rng = random.Random(int.from_bytes(sha256(seed_source.encode()).digest()[:8], "big"))` → `randint(target_min, target_max)` → `shuffle(preferred)` → `shuffle(rest)` → `(preferred + rest)[:target]` → `truncate_voice_profile_to_budget`.
- `config/schema.py` — `ContentConfig.voice_profile_tags: dict[str, list[str]] | None = None`.
- `config/orchestrator_models.py` — mirrored on `OrchestratorContent`.
- `config/source.py` — `voice_profile_tags=ct.voice_profile_tags if ct else None` in `_build_app_config_v2`.
- `config/loader.py` — read from `CONTENT_SETTINGS` in `_load_content_settings_from_env`, passed into the `ContentConfig(...)` construction, and `"voice_profile_tags"` added to `REDACT_KEYS`.
- `core/workflow.py` — the flat `truncate_voice_profile_to_budget(...)` call replaced with `sample_voice_examples(..., seed_source=(selected_content_hash or selected_hash), platform_tags=..., platforms=list(specs.keys()))`.
- `web/service.py` — `_select_voice_examples` gained `seed_source`/`platform_tags`/`platforms`; the call site seeds on `hashlib.sha256(analysis_source).hexdigest()` (in `asyncio.to_thread`) when `analysis_source` is `bytes`, else on `filename`. Both the callee and the call site are gated by a new module-level `_voice_matching_active(config)`, so the default tenant — voice matching off — computes no seed at all and the two call sites mirror each other.
- `web/models.py` — `VoiceProfileResponse.persisted: bool = False`, `orchestrator_field: str = "content.voice_profile"`.
- `web/app.py` — both `api_get_voice_profile` and `api_set_voice_profile` pass those two explicitly. Auth guards untouched.
- `web/templates/index.html` — the save status branches on the response's `persisted`. Falsy or missing (today, always): "Saved N example(s) for this process only (not persisted to the orchestrator — set content.voice_profile there to survive a restart)". Truthy: durably-saved wording naming `orchestrator_field`. An error, a non-2xx or an unparseable body all land on the process-local copy, never on a persistence claim.

### Tests
- `publisher_v2/tests/test_owner_voice_corpus.py` (new) — 7 sampler tests (AC1–AC3).
- `publisher_v2/tests/test_owner_voice_corpus_workflow.py` (new) — 3 end-to-end tests (AC4) through the real `OrchestratorConfigSource` (over `httpx.MockTransport`) and the real `WorkflowOrchestrator`, with faked Dropbox and a recording `AsyncOpenAI`.
- `publisher_v2/tests/web/test_web_settings_voice_profile.py` (extended) — 2 tests (AC5) in `TestVoiceProfileReportsPersistence`.
- `publisher_v2/tests/config/test_loader_json_helpers.py` (one pre-existing test updated — see Notes).

### Docs
- `docs_v2/07_AI/AI_PROMPTS_AND_MODELS.md` §8.1 — the field, all five algorithm steps, both seed sources, the 4–6 target with the budget caveat, redaction, and the multi-platform union semantics.
- `CHANGELOG.md`, `docs_v2/roadmap/README.md`, `docs_v2/roadmap/PUB-050_plan.yaml`, and this file.

## Acceptance Criteria

- [x] AC1 — 4–6 examples from a 12-item profile, no duplicates, all drawn from the profile (`test_sample_voice_examples_returns_four_to_six_from_twelve_item_profile`, `test_sample_voice_examples_result_has_no_duplicates_and_is_drawn_from_profile`)
- [x] AC2 — identical for the same seed, different for two chosen seeds (`test_sample_voice_examples_is_deterministic_for_same_seed`, `test_sample_voice_examples_differs_for_two_chosen_seeds`)
- [x] AC3 — single-platform tag preference, stale tags ignored, multi-platform union (`test_sample_voice_examples_prefers_email_tagged_examples_when_pool_is_large_enough`, `test_sample_voice_examples_ignores_a_tag_whose_text_is_not_in_the_profile`, `test_sample_voice_examples_unions_tags_across_multiple_enabled_platforms`)
- [x] AC4 — the real workflow's prompt carries the per-image sample, not the full profile, in all three cases (`test_workflow_run_prompt_contains_sampled_voice_examples`, `test_workflow_run_prompt_prefers_tagged_examples_when_voice_profile_tags_set`, `test_workflow_run_prompt_unions_tags_when_two_platforms_enabled`)
- [x] AC5 — both verbs report `persisted: false` and `orchestrator_field: "content.voice_profile"` (`test_get_voice_profile_reports_not_persisted`, `test_post_voice_profile_reports_not_persisted`)
- [ ] AC6 — **not satisfied, and believed unsatisfiable as written.** See "AC6 is blocked by a harness gap, not just by sequencing" below.

All 12 pytest function names match the handoff's Test-first targets table verbatim. No test was written for AC6.

### Extra tests beyond the contract (13)
Added while closing review nits; names are not in the handoff table and are recorded here instead:
- `publisher_v2/tests/web/test_web_analyze_voice_seed.py::test_analyze_seeds_voice_examples_on_the_image_bytes_not_the_filename`
- `publisher_v2/tests/web/test_web_analyze_voice_seed.py::test_analyze_gives_the_same_image_the_same_voice_examples_every_time`
- `test_owner_voice_corpus.py::TestUnmatchedTagKeyWarning::test_sample_voice_examples_warns_when_no_tag_key_matches_an_enabled_platform`
- `test_owner_voice_corpus.py::TestUnmatchedTagKeyWarning::test_sample_voice_examples_does_not_warn_when_no_tags_are_configured`
- `test_owner_voice_corpus.py::TestUnmatchedTagKeyWarning::test_sample_voice_examples_does_not_warn_when_a_tag_key_matches`
- `test_owner_voice_corpus.py::TestUnmatchedTagKeyWarning::test_warning_truncates_a_long_tag_key_so_caption_text_cannot_leak`
- `test_owner_voice_corpus.py::TestUnmatchedTagKeyWarning::test_warning_logs_a_real_platform_name_intact`
- `test_owner_voice_corpus.py::TestUnmatchedTagKeyWarning::test_warning_never_logs_tag_values_or_extra_payload_fields`
- `test_owner_voice_corpus.py::TestUnmatchedTagKeyWarning::test_a_non_string_tag_key_does_not_crash_the_warning` (parametrized: int key, None key)
- `test_web_analyze_voice_seed.py::test_analyze_does_not_hash_the_image_when_voice_matching_is_off`
- `test_web_analyze_voice_seed.py::test_analyze_still_hashes_the_image_when_voice_matching_is_on`
- `test_owner_voice_corpus.py::TestUnmatchedTagKeyWarning::test_warning_caps_how_many_tag_keys_it_logs_and_reports_the_real_total`
- `test_web_analyze_voice_seed.py::test_analyze_seeds_on_the_filename_on_the_presigned_url_vision_path`

## Test Results

Full suite, on a tree containing only PUB-050:

```
uv run pytest -q --cov
1847 passed, 1 skipped, 83 warnings
Required test coverage of 85% reached. Total coverage: ~93.0%
```

PUB-050's own surface (25 test functions / 26 test IDs: 12 contract + 13 extra), plus the one touched pre-existing test file: **60 passed**. Also green under `--randomly-seed=1`, `--randomly-seed=424242` and `--randomly-seed=31337`, all measured on this final tree (no isolation defect from the class-level `_FakeOpenAI.captured_messages`, which an autouse fixture resets).

## Quality Gates

- Format: ✅ `251 files already formatted`
- Lint: ✅ `All checks passed!`
- Type check: ✅ `Success: no issues found in 65 source files`
- Tests: ✅ 1847 passed, 1 skipped, 0 failed
- Coverage: **~93.0% overall** (gate 85). Per handoff-required module: `services/ai.py` 95%, `core/workflow.py` 94%, `web/service.py` 83%, `web/app.py` 94%, `config/orchestrator_models.py` 100%, `config/schema.py` 99%, `config/loader.py` 95%, `config/source.py` 86% — all above the 80% floor.

## Subagent Verdicts

Four review rounds ran: two on the initial implementation, a third adversarial pass (fuzz plus integration), and a fourth on the finished state. Every verdict was PASS or PASS WITH NITS — **no blockers at any point**. A fifth review covered the committed state.

### Round 4 (final state)
- `security-auditor`: **PASS** — no nits, the only unqualified verdict of the item. Confirmed the capped payload cannot carry a tag value, that truncate→sort→slice cannot exceed 32 chars, and that the shared-prefix duplicate case is a *monotone loss* of information (it reveals strictly less, never more) with `tag_key_count` preserving the true scale. Also confirmed the presigned-URL seed carries no influence risk worth the name: a planted filename steers only which subset of the tenant's own already-approved examples is preferred, and the filename never reaches a log through that path.
- `code-reviewer`: **PASS WITH NITS** — mutation-proved the guard hoist left the ON path byte-identical (reverting the call-site guard killed only the off-path test), independently reproduced the leak-rate table, the budget thresholds and the five-interpreter determinism claim, and verified every contract test name against the handoff. Its nits were two stale bullets in this summary (fixed), a mislabelled table row and a comment (both fixed), and an untested presigned-URL branch (now tested).

### Round 2
- `code-reviewer`: **PASS WITH NITS** — re-ran every gate on the tree as it stood then (1841 passed / 1 skipped, 93.01%, green under three random seeds) and **mutation-tested the load-bearing tests** rather than reading them: forcing the seed to `filename`, flipping `(preferred + rest)` to `(rest + preferred)`, reverting `workflow.py` to `truncate_voice_profile_to_budget`, and deleting the warning branch each killed exactly the tests that should die, and no others. Confirmed the warning's key-mismatch asymmetry, the `to_thread` narrowing, and that `CaptionSpec.for_platforms()` is absent from the diff. Its four nits were all summary-doc count drift, since corrected, plus the accepted log-volume note below.
- `security-auditor`: **PASS WITH NITS** — found the one real defect of the whole item (the log leak described below) and confirmed everything else: keys-only payload, `json.dumps` escaping ruling out log injection, no REDACT_KEYS bypass, no seed drift or lifetime concern from the `to_thread` lambda, auth unchanged, preview safe, injection block intact, `textContent` (not `innerHTML`) on the new UI string.

### Round 3 — adversarial pass (fuzz + integration)
A third, deliberately adversarial round ran after the two reviews above: a fuzz/property pass against `sample_voice_examples` and an integration pass hunting for what the tests miss. It produced one finding that matters, reproduced and then independently re-measured by the Lead:

**AC3's "large enough to fill the target" threshold is 6, not 4 — and nothing said so.** `target = min(len(pool), rng.randint(4, 6))` is drawn *before* `preferred` is consulted, so a tagged pool smaller than `target_max` leaks untagged examples whenever the draw exceeds it. Measured over 2000 seeds against a 12-item pool:

| tagged pool size | runs containing an untagged example |
|---|---|
| 3 | 100% |
| 4 | 67% |
| 5 | 34% |
| 6+ | 0% |

The rates are exactly `P(target > k)`. The implementation is faithful to AC3's literal wording, and `test_sample_voice_examples_prefers_email_tagged_examples_when_pool_is_large_enough` uses 6 tagged examples, so the suite is green and honest. But an operator reading "four to six examples" would reasonably tag 4 and get an untagged example two runs in three. Documented in §8.1 rather than patched: making preference guaranteed at 4 means clamping `target` against `len(preferred)`, which changes the pinned algorithm and AC2's determinism, so it is a spec decision and is flagged under "Outstanding, needs the user".

**A performance regression this item introduced, now fixed.** `web/service.py` computed the sha256 seed over the whole downloaded image *unconditionally*, before `_select_voice_examples` — which returns `None` immediately when voice matching is off. Voice matching is off by default, so every `/api/analyze` on the default tenant paid a thread hop plus a multi-MB hash for a value that was thrown away. The old code had no such cost (it passed no seed at all), and `core/workflow.py` already guarded correctly. Fixed by hoisting the same guard behind a shared `_voice_matching_active(config)` predicate, so the two call sites now read alike — which is how the gap was found in the first place. Two tests pin it: one that no digest of the image bytes is taken when matching is off, and a positive control that the enabled path still seeds on the bytes (so "fixing" the cost by falling back to the filename seed fails).

**A crash in the diagnostic path.** The unmatched-key warning did `key[:32]`, which raises `TypeError` on a non-string key — so the branch that exists to diagnose misconfiguration was more brittle than the path it diagnoses, which shrugs the same input off. Now `str(key)[:32]`. Unreachable from a real config (Pydantic enforces the annotation), so this is an API-robustness guard on a public function, and the test and comment both say so.

Two smaller items from the same pass, both documented rather than patched:
- **Cross-version determinism is de-facto, not guaranteed.** CPython promises reproducibility only for `random()`/`getrandbits`, explicitly not for `randint`/`shuffle`. Verified byte-identical on CPython 3.10, 3.11, 3.12, 3.13 and 3.14a3 today, so there is no live problem — but a future CPython change would silently re-roll every image's sample with no error and no log. Recorded in §8.1 so the assumption is not invisible.
- **The budget degradation now has numbers.** The roadmap pre-accepts it but says only "reasonably short". Measured: examples averaging under ~300 chars never drop below 4; ~400 chars caps the result at 4; ≥500 chars always returns fewer than 4. §8.1 now gives the operator the number.

**Three docs outside §8.1 were stale or missing and are now fixed.**
- `docs_v2/02_Specifications/ORCHESTRATOR_RUNTIME_CONFIG_SCHEMA_REFERENCE.md` §4.8 had no `voice_profile_tags` row. This is the document the orchestrator implements against, and the roadmap's Scope names the orchestrator as the party that must populate the field — without a row it had no published shape. Added, with notes covering the platform-name-not-publisher-type trap, the union semantics, the tag-at-least-six rule, and that Publisher exposes no write UI for it. No `schema_version` bump needed: every orchestrator model sets `extra="allow"`, so the field is additive-optional in both directions.
- `docs_v2/02_Specifications/SPECIFICATION.md:109` still described the voice block as "budget-truncated via `truncate_voice_profile_to_budget`", which is no longer how either call site builds the list. Corrected in place.
- §8.1's redaction sentence claimed the fields are "redacted from structured config logs". Overstated: `REDACT_KEYS` feeds only `_safe_log_config`, which has **no production callers** and matches top-level keys only. Softened to say what is true, and to point at the truncated-key warning as the protection that actually applies today.

**The warning payload is now bounded in both dimensions.** A round-3 audit nit: `voice_profile` is capped at 20 entries by its validator, but `voice_profile_tags` has no size cap at all — so the very misconfiguration this warning diagnoses is also the one that could make it enormous, once per image, indefinitely. Now `MAX_LOGGED_TAG_KEYS = 10` caps the listed keys, and an unconditional `tag_key_count` carries the real total so a truncated list is recognisable as one and the true scale stays visible. Documented in §8.1.

**The last redaction overclaim is gone.** `config/loader.py`'s module docstring still asserted, unqualified, that anything matching `REDACT_KEYS` is masked before config is logged — the exact claim §8.1 had just been corrected to stop making. Now scoped to what the code does: `_safe_log_config`, on dicts actually passed through it, top-level keys only.

**The UI now reads `persisted` instead of assuming it.** `index.html`'s status line hard-coded the process-local wording while reading only `orchestrator_field`. True today, but `persisted` was added to the response precisely so the UI would not have to assume, and persistence is flagged as a decision that may flip. It now branches: falsy or missing → today's wording unchanged; truthy → durably-saved wording naming the field. A missing flag degrades to the process-local copy rather than claiming persistence. Still `textContent`, error paths untouched.

**Left alone deliberately.** `core/workflow.py` seeds on `selected_content_hash or selected_hash`, both initialized to `""`. If neither were populated every image would draw the identical sample — but all three real selection paths set `selected_hash`, and the idiom matches the existing `lease_hash` line directly above. Defensive only, no change made.

Also corrected: an earlier note in this summary said tag keys have "no validator". Pydantic enforces the `dict[str, list[str]]` annotation at both config entry points, so keys are always `str` and the crashing shapes (non-str key, non-list value) cannot reach the sampler from a real config. Only the key's *content* is unconstrained — which is what the 32-char truncation addresses.

### Known, accepted
For a persistently misconfigured tenant the `voice_profile_tags_matched_no_enabled_platform` warning fires once per image, indefinitely. Accepted as-is: a once-per-process guard was considered and rejected, because a warning that appears once and then goes quiet is easy to miss, and the payload is now bounded and non-sensitive. Revisit if log volume becomes a real cost.

### Round 1
- `code-reviewer`: **PASS WITH NITS** — all 8 checks faithful to the contract; gates re-run independently; verified the `platforms` argument order cannot influence output and that the tags-but-no-match path is byte-identical to the untagged path.
- `security-auditor`: **PASS WITH NITS** — redaction effective (`_safe_log_config` matches keys by exact lowercase equality and the literal is exactly lowercase); no other log or HTTP path exposes the tags (`/api/config` never returns them, so they are strictly *less* exposed than `voice_profile`); `require_admin` → `require_auth` unchanged in presence and order on both verbs; preview stays side-effect free; no secrets, and no secret material in the RNG seed; `build_voice_examples_block`'s hardened BEGIN/END block not bypassed.

Nits raised and **fixed** during review:
- `services/ai.py` — `rest = pool` aliased the pool, so `rng.shuffle(rest)` shuffled `pool` in place. Harmless today, a trap for any future edit reading `pool` after the shuffle. Now `rest = list(pool)`; determinism unchanged (identical contents, identical RNG draws), all tests re-verified.
- `test_owner_voice_corpus_workflow.py` — the fake OpenAI branched on `"sd_caption" in str(user)`, which PUB-051 AC4 removes from this prompt; the AC4 tests would then have failed looking like a sampler regression. Now branches on a new `MULTI_CAPTION_MARKER = "Generate captions for these platforms:"`, emitted unconditionally by `_build_multi_prompt` above the platform blocks, plus a loud guard that fails with "marker is stale" rather than silently. Verified by simulating the post-PUB-051 prompt (passes) and by a control run with the old marker under the same simulation (fails).

Remaining three nits, also **fixed** in a follow-up round:
- `web/service.py` — the sha256 over image bytes now runs in `await asyncio.to_thread(...)`; the ternary became an explicit `isinstance` branch binding `image_bytes` inside the narrowed arm, because mypy does not carry `isinstance` narrowing into a lambda closing over a `str | bytes`. The filename branch never enters a thread and the seed value is byte-identical.
- The bytes-vs-filename seed branch is now tested (`test_web_analyze_voice_seed.py`, 2 tests). Verified branch-sensitive: forcing the seed to `filename` in a scratchpad monkeypatch makes the first test fail.
- `sample_voice_examples` no longer degrades silently when a tag **key** names no enabled platform: it logs a WARNING `voice_profile_tags_matched_no_enabled_platform` carrying only `tag_keys` and `enabled_platforms` (never tagged text or profile content). Documented in §8.1.

**A leak the warning itself introduced, then closed.** The final security audit caught that the new warning logged `voice_profile_tags` keys verbatim. Pydantic does enforce the `dict[str, list[str]]` annotation on both `ContentConfig` and `OrchestratorContent`, so a key is always a `str` — but there is no validator on its *content*, so a key can be arbitrary text of any length. The warning fires *precisely* in the misconfiguration case, and the most plausible misconfiguration is an inverted mapping (`{"<a whole example caption>": ["telegram"]}`) — which would have spilled operator caption text into tenant logs at WARNING, once per image, forever. Fixed: keys are now truncated to `MAX_LOGGED_TAG_KEY_CHARS = 32` (a plain prefix, no ellipsis) in the payload. Long enough to name any real platform intact, far too short to carry a caption. Three tests pin it, including one asserting the full key text never reaches the log and one asserting `tag_keys == ["instagram"]` so the cut costs nothing diagnostically. §8.1 states the truncation and its reason.

**Lead decision on the warning's trigger.** It keys on *no tag key matched an enabled platform*, not on *`preferred` ended up empty*. The latter would also fire for a tag key that matches but whose listed text is no longer in `voice_profile` — which the roadmap explicitly specifies as a silent ignore. The asymmetry is deliberate and is stated in §8.1 so the doc does not imply every tag problem is logged.

## Notes

### Judgment calls not spelled out in the spec (both endorsed by review)
1. **No Pydantic validator on `voice_profile_tags`.** The spec requires a tag whose text is absent from `voice_profile` to be *ignored, not an error*; the sampler filters the tag union against pool membership instead. `validate_voice_profile` is validation-only and does not normalize strings, so exact-string matching is sound — there is no sanitization-drift trap. Type-level malformation still raises at config load, mirroring `voice_profile`.
2. **Tags present but matching no enabled platform** falls back to `preferred=[]` / `rest=pool`, identical to the untagged path. `random.shuffle` on an empty list consumes no RNG state, so the output is byte-identical — this is exactly spec step 2's "Otherwise" branch.

### One pre-existing test changed
`test_loader_json_helpers.py::TestRedactKeys::test_redact_keys_contains_expected_keys` pinned `REDACT_KEYS` by exact set equality and so broke on the spec-mandated addition. The Lead resolved this as a stale change detector, not a code defect: `_safe_log_config` (`config/loader.py:119-122`) matches keys by exact lowercase equality, **not** substring, so without its own entry `voice_profile_tags` would be logged in the clear beside a redacted `voice_profile`. `"voice_profile_tags"` was added to the expected set; the strict exact-equality assertion was deliberately **kept**, since it is a change detector for a security-relevant constant. No other pre-existing test was weakened.

### Left untouched on purpose
`CaptionSpec.for_platforms()` (`core/models.py`) is byte-identical — it still assigns the full unsampled profile into each spec's `examples` tuple. The roadmap forbids cleaning this up and forbids describing it as unreachable in a comment; both real call sites now always pass explicit `voice_examples`, so the fallback is *reached but empty*, not dead.

### AC6 is blocked by a harness gap, not just by sequencing
The spec assumes AC6 is merely waiting on PUB-049 to ship. PUB-049 *has* shipped (merged as #225, `431cbeb`), and AC6 still cannot be satisfied — because the harness's generation path never reaches the sampler this item adds:

- `scripts/caption_eval.py:429-430` calls `create_multi_caption_pair_from_analysis(analysis, specs, history=history)` with **no `voice_examples` argument**.
- `scripts/caption_eval.py:164-177` (`build_specs`) hand-builds each `CaptionSpec(... examples=(), ...)` rather than going through `CaptionSpec.for_platforms(config)`.

So the harness generates captions with no voice examples at all, by either route. A before/after `--nightly` run would show a **zero delta** attributable to PUB-050 no matter what corpus #179 eventually supplies. Satisfying AC6 as written first requires teaching the harness to exercise the voice path — which would change PUB-049's harness and invalidate its committed `snapshot.json` and `caption_eval_thresholds.json`, and is out of scope here. Flagged for re-specification rather than silently skipped or unilaterally fixed.

Separately, `--nightly` regenerates the snapshot through the real publish pipeline, i.e. live OpenAI calls; it was not run in this session.

### Note (historical, pre-commit)
Concurrent PUB-051 test-first work was present in this tree mid-implementation and was later withdrawn by whatever placed it there. A separate worktree, `SocialMediaPythonPublisher-pub051`, exists on its own branch and is the likely origin. The work is committed now; PUB-051's spec and handoff were deliberately left out, as were the `.claude/agent-memory/` files a reviewing subagent wrote.

### Known, outside this item's scope
`detect-secrets` (pinned v1.4.0) reports three new hits against `.secrets.baseline` — `PUB-050_handoff.md:71` (the prose bullet naming `REDACT_KEYS`) and two fixtures in `test_owner_voice_corpus_workflow.py` (a pinned fake content hash, an opaque `password_ref`). All three are false positives. The baseline is **already stale on `main`** with four pre-existing hits of its own, so refreshing it would sweep those in too — left for a deliberate, separate baseline-refresh commit rather than folded in here.

`sample_voice_examples`'s `return []` empty-examples guard is the one line this item added that no test covers. Both production call sites guard on a truthy `voice_profile` before calling, so it is genuinely defensive — recorded so it is not later mistaken for a coverage gap.

### Outstanding, needs the user
The spec's own "Outstanding Issues" section asks for two confirmations that were never explicitly given; the handoff had already locked both in, so implementation proceeded on that reading:
1. **AC5 persistence** — implemented as `persisted: false` only, with no orchestrator write-back endpoint. If the setter should actually persist, that needs its own item on the orchestrator side first (contract owner).
2. **Effort S → M** — the roadmap index row was updated to M to match the spec.
