---
name: voice-corpus-sampler-review-traps
description: PUB-050 review traps — unvalidated config dict KEYS leak into log_json (REDACT_KEYS does not cover it), caption_eval harness never passes voice_examples, and the working tree can change mid-review
metadata:
  type: project
---

PUB-050 (`sample_voice_examples`, `services/ai.py`) review findings worth carrying forward.

**Why:** each one cost a full extra verification round on 2026-09-25 and none is visible from
reading the diff alone.

**How to apply:**

1. **`REDACT_KEYS` only protects `_safe_log_config`.** It matches by exact lowercase key equality
   in the config-dump path. Any *other* `log_json(...)` call that passes config-derived data is
   unprotected. PUB-050 logged `tag_keys=sorted(platform_tags)` — and `voice_profile_tags` keys
   have no validator, so an inverted map `{"<a whole caption>": ["telegram"]}` printed owner
   caption text at WARNING once per image. Fixed by `key[:MAX_LOGGED_TAG_KEY_CHARS]` (32, plain
   prefix). Whenever a new log event carries operator free-text keys or values, check the value's
   validator, not just `REDACT_KEYS`.
2. **The PUB-049 harness cannot observe any prompt-input feature.** `scripts/caption_eval.py`
   `build_specs` hand-builds `CaptionSpec(... examples=(), ...)` instead of
   `CaptionSpec.for_platforms(config)`, and its `create_multi_caption_pair_from_analysis(...)`
   call passes no `voice_examples`. So a before/after harness run shows a zero delta for anything
   that only changes voice examples. Any roadmap AC of the form "prove it with the harness" is
   unsatisfiable until the harness is taught the path.
3. **`_build_multi_prompt` promotes `spec.examples` only when `voice_examples is None`.** An
   empty list is treated as a deliberate decision, not an absence — so `CaptionSpec.for_platforms`'s
   full profile is "reached but empty", not dead code (the roadmap forbids calling it unreachable).
4. **The working tree can change while you review.** During this pass, tests and then source were
   edited under me twice; a verdict written from the first read would have been wrong in both
   directions (missed 3 tests, then wrongly reported red). `stat -f "%Sm %N"` / `find -newermt`
   the touched files after the last gate run and before writing the verdict.

5. **A per-image seed computed before the feature guard is a real cost regression.** PUB-050's
   first cut hashed the whole image (sha256, thread hop) in `web/service.py`'s analyze path and
   then called `_select_voice_examples`, which returns `None` when voice matching is off — the
   default. Fixed by a module-level `_voice_matching_active(config)` predicate used at both the
   guard and the call site. Whenever a new prompt feature needs a per-image seed, check the
   *caller* guards on the feature flag, not just the callee.
6. **Tag preference leaks are exact arithmetic, not folklore.** `target = min(len(pool),
   rng.randint(4, 6))` is drawn *before* `preferred` is consulted, so P(an untagged example
   appears) = P(target > len(preferred)) = 1, 2/3, 1/3, 0 for 3, 4, 5, 6+ tagged. Reproduced over
   2000 seeds. The operator-facing rule is "tag at least six per platform".
7. **`random.Random.randint`/`shuffle` cross-version determinism is de-facto only.** CPython
   guarantees it for `random()`/`getrandbits()` only. Reproduced byte-identical on 3.10-3.14a3
   (2026-09) with `uv run --python <v> --no-project`; cheap to re-verify, so do.

Related: [[mutation-check-review-technique]], [[caption-eval-harness-review-traps]],
[[config-env-only-review-traps]].

## Added after the committed-state review (2026-09-26)

8. **`detect-secrets scan --baseline .secrets.baseline` REWRITES the baseline.** A read-only
   reviewer must use `detect-secrets-hook --baseline .secrets.baseline <files>` instead (exit
   code only, no write). If you already ran `scan`, `git checkout -- .secrets.baseline`.
9. **The `.secrets.baseline` is already stale on `main`** (4 un-baselined false positives:
   `test_library_delete_sanitizing.py:68,69,73`, `scripts/caption_eval.py:110`, checked with the
   pinned v1.4.0). New prose containing words like "Secrets:"/"REDACT_KEYS" in a roadmap/handoff
   md trips the Secret Keyword plugin. Calibrate severity against main before calling it a
   blocker — and note `.git/hooks/pre-commit` is not installed locally, so commits do not run it.
10. **Archiving convention: plan + summary move to `archive/` too.** PUB-045/046/047/048 all have
    `archive/PUB-NNN_plan.yaml` and `archive/PUB-NNN_summary.md`. PUB-049's tidy-up moved only the
    spec and deleted its handoff, leaving plan/summary in the active roadmap dir. Check this on
    any commit that claims to "finish the post-merge paperwork".
11. **A `/product-harden` spec rewrite can be uncommitted and get swept into the implementation
    commit.** PUB-050's commit 1 carries the entire hardened spec (the contract) with no mention
    in the message. Always `git diff main...HEAD -- docs_v2/roadmap/PUB-NNN_<slug>.md` and check
    whether the contract itself moved inside the implementation commit.
