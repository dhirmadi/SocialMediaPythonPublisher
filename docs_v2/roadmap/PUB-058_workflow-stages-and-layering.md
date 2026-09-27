# PUB-058: Workflow Stages and Layering

| Field | Value |
|-------|-------|
| **ID** | PUB-058 |
| **Category** | Foundation |
| **Priority** | P1 |
| **Effort** | L |
| **Status** | Proposal |
| **Dependencies** | PUB-047, PUB-054 |

## User Story

As a platform maintainer, I want the publish pipeline to be a sequence of small stages that the CLI and the web service both run, with the layering rule enforced in both directions, so that the next correctness fix is a change to one stage rather than another branch in a 766-line function.

## Problem

`core/workflow.py:308` `WorkflowOrchestrator.execute()` is 766 lines (649 when #207 was filed; one `try` then spanned 523 lines, with eight nested `try`, max indent ten and 27 locals pre-declared); `_select_image` is 171 lines. `web/service.py:794` `_analyze_and_caption_impl` is a 275-line second copy of analyze, caption and sidecar, and `publish_image` a 99-line second copy of publish. Stage boundaries are discoverable only from `log_json` event names. Since #207 was filed, PUB-051 added sidecar-reuse and override-angle logic inside `execute` (`_reuse_generated_captions`, `_override_angles`, `_read_sidecar_view`, and a sidecar write when captions were generated but there is no SD prompt). Both lazily import the sidecar module, both build `CaptionSpec.for_platforms`, both pick a primary caption; caption selection was rewritten three times in 48 hours (#103, #147, #134). Every weekend fix added branches inside `execute` (#139 alone +173 lines). The lease-TTL, cancellation and partial-publish invariants are enforced by one `finally` over 523 lines of state. Layering: `tests/test_layering.py:34-43` enforces only that nothing below web imports web; `core/workflow.py:32-33` imports concrete `services.ai` and `services.publishers.base` at module level, and function-level imports reach `services.ai`, `services.sidecar`, `services.sidecar_parser` and `services.publishers._sanitize`; `core/models.py:79` lazily imports `config.static_loader` inside `CaptionSpec.for_platforms`, so the domain model reads a global cache; `config/` imports `core.exceptions` in 5 files (`loader.py`, `source.py`, `orchestrator_client.py`, `runtime_settings.py`, `web_env.py`); `utils/captions.py:8-9` and `utils/preview.py:7-10` import config, core and publishers; outside `core`, `services/instagram_session.py` imports `db` inside methods, the storage-ops and usage meters import `config.orchestrator_client` inside functions, and `web/app.py` imports `config.schema` inside a route body. 46 lazy intra-package imports (count at #208 filing) keep the lattice cycle-free. `ARCHITECTURE.md:11-19` claims dependency inversion the code does not practise.

## Desired Outcome

A `RunState` dataclass and seven stages (Select, Analyze, Caption, Sidecar, LeaseAndPublish, Archive, Record), each under 80 lines, with `execute` reduced to the stage list, the deadline and the `finally`. The web service runs the same stages. Six characterisation scenarios recorded before the extraction pass unchanged after it. The layering test enforces both directions and a falling ratchet on lazy imports.

## Scope

**In scope:**
- Characterisation PR first: log-event and fake-client call sequences for happy path, preview, partial publish, retry after partial, lease expired, archive failure, through the real orchestrator (`tests/test_workflow_characterisation.py`)
- `RunState` dataclass (selection, bytes, content hash, temp path, analysis, spec, captions, variants, leases and tokens, publish results, timings, deadline); one PR per stage moving code without behaviour change; log event names preserved
- Stage extraction preserves PUB-051's sidecar-reuse and override-angle behaviour (`_reuse_generated_captions`, `_override_angles`, `_read_sidecar_view`, and the sidecar write when captions were generated without an SD prompt)
- `execute` keeps only the ordered stage list, the deadline and the `finally` (lease release, cleanup)
- Web service routed through the same stages (`analyze_and_caption` runs Analyze, Caption, Sidecar; `publish_image` runs LeaseAndPublish, Archive, Record); duplicated code deleted; caption selection in one module
- `_select_image` split into listing, hashing and candidate filtering, each under 80 lines
- `ConfigurationError` moved into `config/exceptions.py`, re-exported from `core.exceptions` for one release; `utils/captions.py` and `utils/preview.py` moved under `services/`; `CaptionSpec.for_platforms` takes platform styles as a parameter, passed by callers from config; `WorkflowOrchestrator` receives a sidecar writer and error sanitiser by constructor (protocols in `services/*_protocol.py`), and its function-level service imports go
- `test_layering.py`: core imports only protocols and `publishers.base`; utils imports only utils; config does not import core; lazy-import count ratchet (starts at the current count, may only fall)
- Docs: `.claude/rules/architecture.md` describes the stage pipeline and working rule 3; `docs_v2/03_Architecture/ARCHITECTURE.md:11-19` layering claim rewritten to match the test; a new ADR for the stage pipeline

**In scope (absorbed 2026-09-27 from the DRY review, [#291](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/291)):**
- The `_select_image` split deletes the legacy "SHA256-only" branch rather than carrying it: `supports_content_hashing()` leaves the protocol and both backends (only test dummies returned `False`; they return `(name, None)` hashes instead); an `_ImageSelection.fail(...)` constructor replaces the seven hand-spelled error selections ([#284](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/284))
- `RunState` carries `live = not debug and not dry_publish and not preview_mode`, computed once (today nine copies); the four `if not preview_mode: log_json(...)` guards go (preview already logs at WARNING) ([#284](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/284))
- Dead code deleted as its module moves: `WorkflowResult.dropbox_url`, `db.get_engine`, the in-place mode of `ensure_max_width` ([#284](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/284))
- The Caption stage calls `create_multi_caption_pair_from_analysis` directly: the `hasattr` probes in workflow and web, the single-platform SD path (`generate_with_sd`, `create_caption_pair_from_analysis`, the SD prompt branches in `AIService.__init__`, `SD_LONG_TEMPERATURE`, `SHORT_LIMIT_MAX_TOKENS_SINGLE_SD`, `_NullGenerator.generate_with_sd`, the SD block in `ai_prompts.yaml`) and the publisher's read of `sd_caption_single_call_enabled` are deleted (contract removal is PUB-057 step 5); the three timeout-to-`AIServiceError` wrappers become one `_within_deadline(coro, deadline)`; the keyed `build_analysis_context` and `_build_inline_hashtags_clause` merge into the prose renderer and one hashtag instruction, with a harness run in the PR because prompt text changes; the PR decides whether web's catch-all single-caption retry stays ([#280](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/280))

**Out of scope:**
- Web app factory and routers (PUB-059)
- Typed platform captions (PUB-059), though the stages should accept the new type when it lands

## Acceptance Criteria

- AC1: Given the six characterisation scenarios, when they are recorded on `main` before any extraction, then each asserts the exact ordered log-event names and fake-client calls
- AC2: Given each stage-extraction PR, when the characterisation suite runs, then it passes with no edits
- AC3: Given `core/workflow.py` and `web/service.py` after the last PR, when function lengths are measured, then none exceeds 80 lines (ratchet test falls with each PR)
- AC4: Given the web analyze and publish paths, when they run, then they execute the same stage classes the CLI runs, and `web/service.py` contains no analyze, caption or sidecar logic of its own
- AC5: Given the extended layering test, when it runs on `main` before this item, then it fails with the exact edge list from the review; when the item is done, then it passes
- AC6: Given a future fix, when it touches `execute` or the web analyze path, then working rule 3 on #177 applies: a stage is added or edited, no branch is added
- AC7: Given the log events emitted by the CLI and web paths, when the last extraction PR has merged, then every `log_json` event name is unchanged
- AC8: Given `core/`, when its imports are walked (module level and function level), then it imports no concrete service, only `services.*_protocol` modules and `services.publishers.base`
- AC9: Given the lazy intra-package import ratchet, when the item is done, then it is in `test_layering.py` and its count is lower than when the item started
- AC10: Given `.claude/rules/architecture.md` and `ARCHITECTURE.md`, when the item is done, then the rules file describes the stage pipeline and working rule 3, and the `ARCHITECTURE.md` layering claim matches what `test_layering.py` enforces
- AC11: Given `src`, when it is searched, then `supports_content_hashing`, `generate_with_sd`, `create_caption_pair_from_analysis` and any `hasattr` probe on the AI service or generator are absent, and the live-run predicate is computed once
- AC12: Given the PUB-049 harness, when the PR removing the single-platform path and merging the renderers is written, then its body records a live run (PUB-080 baseline) showing no regression
- AC13: Given this item ships, when its implementing PRs merge, then [#284](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/284) and [#280](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/280) are closed with `Closes #N` in the PR body (PUB-054 carries the posted-state part of #284, PUB-052 and PUB-057 the rest of #280)

## Implementation Notes

- Two sub-issues: #207 (stages, Phase 4 order 03), #208 (layering, order 04, after #207). Starts only after every Phase 1 and Phase 3 PR that touches `core/workflow.py` or `web/service.py` has merged.
- Characterisation runs through the real `WorkflowOrchestrator` with fakes at the client boundary; it is its own PR with no production change.
- The stage-extraction PRs keep PUB-051's retry path green: a partial retry reuses the captions the first run wrote to the sidecar, override angles still apply, and the sidecar is still written when there is no SD prompt. Add these to the characterisation suite if the six scenarios do not already reach them.
- Verification: `uv run ruff format --check . && uv run ruff check .`, `uv run mypy publisher_v2/src --ignore-missing-imports`, then `WEB_SESSION_SECRET=x uv run pytest -q -p no:cacheprovider` on `test_workflow_characterisation.py`, `test_layering.py` and the full suite.
- Preserve `log_json` event names byte for byte; dashboards read them.
- Stages are plain classes with `async def run(self, state)`; no framework.

## Risks

- The extraction is the largest behaviour-preserving change in the repo's history; the characterisation suite is the only protection, so it must be written adversarially (record the failure paths, not just the happy path).
- Moving `utils/captions.py` touches many imports; do it as a `git mv` with a re-export shim for one release.

## Success Metrics

- Longest function in `core/` and `web/` under 80 lines.
- Lazy intra-package imports fall from 46 to under 10.
- The next publish-path bug fix is a diff to one stage file.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issues [#207](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/207), [#208](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/208)
- [ADR index](../03_Architecture/adr/README.md) — a new ADR for the stage pipeline is recorded with #207
- Prior fixes #96 (layering restore), #85, #139, #143, #147 (branches added to `execute`); PUB-051 (sidecar reuse and override angles added to `execute`)
- [#207](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/207) and [#208](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/208) folded into this spec on 2026-09-27; every requirement and acceptance criterion from both issues is captured above, and the issues can be closed as tracked here.
- 2026-09-27 DRY review [#291](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/291): [#284](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/284) and the code side of [#280](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/280) absorbed (Scope, AC11-AC13)

## Change Log

- 2026-09-27 — Roadmap review: noted that line numbers and PUB-051 sidecar-preservation detail in Problem/Scope are implementation guidance that should be re-verified in the handoff, not hardcoded in the spec — they drift as prior items land.
- 2026-09-27 — Folded in #207 and #208: added the `RunState` field list, the `finally` contents, the web stage mapping, the `config/exceptions.py` move with a one-release re-export, constructor-injected protocols in `services/*_protocol.py`, the ratchet rule, the docs deliverables (rules file, `ARCHITECTURE.md`, ADR), AC7-AC10, ordering and verification. Refreshed numbers from an AST audit at `main` 949b2d1 (`execute` 766 lines, `_select_image` 171, `_analyze_and_caption_impl` 275, `config/` imports `core.exceptions` in 5 files) and recorded PUB-051's additions to `execute` that the extraction must preserve.
- 2026-09-27 — Absorbed #284 (dead legacy selection branch, nine live-run guards, dead aliases) and the code side of #280 (dead single-platform caption path and fallbacks) from the DRY review (#291); added AC11-AC13.
