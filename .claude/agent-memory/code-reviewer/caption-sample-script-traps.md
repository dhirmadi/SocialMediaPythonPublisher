---
name: caption-sample-script-traps
description: "#146 caption evidence traps — PV2_STATIC_CONFIG_DIR beats mutating config/static; tenant OPENAI_SETTINGS prompts silently override static YAML; _sanitize_for_fetlife lost its only test"
metadata:
  type: project
---

Traps found reviewing `scripts/caption_sample.py` (#146, 2026-09-20):

- **`PV2_STATIC_CONFIG_DIR`** (`config/static_loader.py:270`) redirects the static-YAML root. Any "run with an older prompt config" tooling should set that env var + `get_static_config.cache_clear()` instead of `rmtree`/`copytree` over the live `publisher_v2/src/publisher_v2/config/static` — mutating the source tree is unrecoverable if the process is SIGKILLed.
- **Static YAML prompts are a *fallback*, not the source of truth**: `CaptionGeneratorOpenAI.__init__` only applies `static_prompts.caption.system/role` when the tenant config equals `OpenAIConfig()` defaults. If `OPENAI_SETTINGS` JSON carries `system_prompt`/`role_prompt`, swapping ai_prompts.yaml is a no-op for captions (vision prompts at ai.py:424 have no such override and always come from YAML).
- The email caption limit lives in three places that must agree: `platform_limits.yaml` email.max_caption_length, `ai_prompts.yaml` platform_captions.email.max_length, `utils/captions.py::_MAX_LEN["email"]` (line 52). `_MAX_LEN` is only a fallback (`static_limits... or _MAX_LEN[...]`).
- `_sanitize_for_fetlife` (em dash → " - ", smart quotes, ellipsis) and the non-smart email hashtag strip had their **only** test in `test_captions_platform_limits_static.py`; a rewrite of that file deletes that coverage silently (`test_pub028` only covers `smart_hashtags=True`).

**Why:** these are the load-bearing, non-obvious facts behind the #146 review findings.
**How to apply:** on any diff that swaps prompt config, compares before/after captions, or edits the email length, check these four points first.

## Round 2 (2026-09-20, PR #165 abad715) — running the baseline commit's own code

- **The named baseline `5c086e6` predates two APIs the worker uses**: `AIService.aclose` (added
  989f9e1, 2026-09-19) and byte input to `VisionAnalyzerOpenAI.analyze` (the bytes restriction was
  removed in 6c0641d; at 5c086e6 `analyze` raises `AIServiceError("Byte input not supported in V2
  analysis; provide a temporary URL.")`). Any "run the old commit's code in a subprocess" tooling
  must feature-detect, not assume today's signatures. Proven by extracting the commit with
  `git archive <sha> | tar -x -C <scratch>` (read-only — no `git worktree add` in the user's repo)
  and driving the helper with placeholder env.
- **PYTHONPATH does win** over the repo's editable install: `.venv/.../_editable_impl_*.pth` is a
  plain path line (appended after PYTHONPATH), not a meta-path finder, and
  `publisher_v2/src/publisher_v2/__init__.py` exists at the baseline so the regular package beats
  the cwd namespace portion. Verified empirically, not assumed.
- **Error strings bypass the Markdown escaper**: `_render` passes `row.error` in raw while captions
  go through `_cell`; a subprocess stderr tail is multi-line and pipe-bearing, so it breaks the
  table. A single-line error in the test cannot catch it.
- **A worktree-checkout test whose throwaway repo's working tree equals HEAD cannot fail**: mutating
  `into / STATIC_REL` to `REPO_ROOT / STATIC_REL` stayed green. Make the working copy differ from
  the committed copy, and pass a non-HEAD sha.

## Round 3 (2026-09-20, PR #165 f2d00ce) — what the re-review proved

- The three round-2 blockers are genuinely fixed: mutating `getattr(ai, "aclose")` back to
  `await ai.aclose()`, forcing bytes instead of the data URL, `vision_max_dimension` 0 -> 1024,
  and `vision_fallback_enabled` False -> True each turn
  `test_the_worker_runs_against_the_real_baseline_commit` red, with a distinct error.
- **That test needs the live OpenAI endpoint.** With `OPENAI_BASE_URL=http://127.0.0.1:9/v1` it
  fails after 7.5s of tenacity retries; with a *valid* `OPENAI_API_KEY` exported it makes real paid
  calls and then fails `DID NOT RAISE`. All four mutations above still surface their own error when
  the endpoint is unreachable, so asserting "a connection error, not an API mismatch" keeps the
  evidence and makes it hermetic and free.
- The `_cell(row.error)` escaping fix has **no test**: reverting both sites leaves the file green,
  because both error-row tests use a pipe-free, newline-free error string.
- `vision_max_dimension=0` for the baseline half vs the default 1024 for the current half means
  the two halves send *different* vision payloads (full-size original vs 1024px re-encoded JPEG).
  Only `vision_detail="low"` (the default) keeps that from mattering.

## Round 4 (2026-09-20, PR #165 51a791a) — the worker is stub-testable

- **`_BASELINE_WORKER` can be pinned offline, no key, no network.** It only imports four
  `publisher_v2` names (`config.loader.load_application_config`, `config.static_loader.
  get_static_config`, `core.models.CaptionSpec`, `services.ai.{AIService,VisionAnalyzerOpenAI,
  CaptionGeneratorOpenAI}`). A ~30-line stub package on PYTHONPATH drives it end to end in 0.1s
  and lets the test assert the JSON line it prints — including `history_used`, the data-URL vs
  bytes branch and the `getattr(ai, "aclose")` branch. "Only a live key reaches that line" is
  false for this worker; the caller-side refusal is NOT a sufficient boundary, because a worker
  that always claims `history_used: True` defeats the guard and no caller-side test can see it.
- **A guard that only fires from image 2 onward is not a cost guard.** `run()`'s
  `SystemExit` abort is conditioned on *no previous baseline captions*, so any refusal raised
  after image 1 (the `history_used` one is, because image 1 has no history) just marks rows as
  errors and keeps paying both halves for every remaining image. Baseline-capability checks
  belong before the loop, statically, like `_baseline_analyze_wants_url`.

## Round 5 (2026-09-20, PR #165 e4a2bbf) — what survived the fourth pass

- **`_fill_unused_env()` writes `os.environ` directly and has no undo.** Any test that calls it
  leaks placeholder secrets (`DROPBOX_*`, `TELEGRAM_BOT_TOKEN`, `EMAIL_PASSWORD`, …) into the rest
  of the random-ordered session. `monkeypatch.delenv(name, raising=False)` records *no* undo for a
  name that was already absent, so delenv alone does not protect — the caller must
  `monkeypatch.setenv(name, "")` first (`_fill_unused_env` treats `""` as unset, so the fill still
  runs). `test_the_documented_invocation_supplies_every_required_variable` does this;
  `test_it_refuses_to_start_without_a_key` (which reaches the fill before its SystemExit) does not,
  and still leaks 5 vars. Detect it with a throwaway `test_zzz_leakcheck.py` appended to the run.
- **`_baseline_takes_history` text parser is empirically sound for this repo**: checked against all
  44 revisions of `services/ai.py`, it agrees with an `ast.parse` ground truth every time. Its only
  *unbounded-cost* failure mode is a false positive (a `history`-ish substring in an otherwise
  history-free signature, e.g. `history_by_platform`, or a `# history …` comment inside the param
  list), because that passes the pre-flight and then the runtime refusal cannot abort — image 1 has
  no history, so `run()`'s "never produced anything" abort condition is already false by image 2.
  False *negatives* (a `)` before `history`, an earlier docstring/comment mention) merely refuse the
  run, and a missing marker/file fails open at a cost of at most one baseline image.
- The worker stub (`_stub_publisher_v2`) is hermetic because **PYTHONPATH beats the venv's editable
  `.pth`**; the assertion that keeps it honest is `result["captions"] == {"telegram": "stub"}`, which
  only the first of the three class tests makes.
