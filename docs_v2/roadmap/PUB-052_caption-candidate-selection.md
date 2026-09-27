# PUB-052: Caption Candidate Selection and Model Trial

| Field | Value |
|-------|-------|
| **ID** | PUB-052 |
| **Category** | AI |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Not Started |
| **Dependencies** | PUB-049 (Done), PUB-051 (Done) |

## User Story

As a publisher operator curating content, I want the pipeline to generate a few candidate captions and keep the one least like what was posted recently and least like a machine, so that diversity is something the system does on every run rather than a gate that never fires.

## Problem

`services/ai.py` generates once via `_generate_once` (a closure inside `create_multi_caption_pair_from_analysis`, ~line 1800), scores each platform against history with trigram Jaccard via `_apply_similarity_gate` (~line 1828), and regenerates with a diversity clause if any score exceeds `CAPTION_SIMILARITY_THRESHOLD = 0.45` (line 121). PUB-049 establishes that the metric scores real clones at 0.04, so the gate fires only on near-verbatim reuse, which a 0.9-temperature model (PUB-051's setting) essentially never produces; the `caption_similarity` telemetry (~line 1890) reports comfortable diversity forever, and when the gate does fire the regeneration re-picks the content angle via `pick_content_angle` (PUB-051's replacement for the old `pick_structure_directive`). Both web (`web/service.py:954`) and cron (`core/workflow.py:609`) now use `angle_history_depth(window_size)` as their limit — but the text-based history window is still `window_size=3` (the default in `CaptionHistoryConfig`), not the 30 needed for selection. Separately, `caption_model` is gpt-4o-mini (`config/schema.py:85`), the cheapest 2024 model; the name validator now accepts any model (#81), so a trial is a config change, but done before the pipeline is repaired a better model would hide whether the pipeline improved.

## Desired Outcome

Every run requests three candidates and selects per platform by lowest tells score and largest TF-IDF-bigram distance from the last 30 captions, logging the scores and the winner. The trigram gate, its threshold and the regeneration loop are gone. Web and cron use the same history depth. After that lands, one alternative model is trialled on the same fixture and the owner reads both sets blind.

## Scope

**In scope:**
- `n=3` (or three temperatures if `n` is unsupported with JSON mode for the configured model; the PR states which)
- Selector using `utils/caption_metrics.py` with a fixed weighting; `caption_candidate_selected` log event with per-candidate scores
- Removal of the trigram gate, `CAPTION_SIMILARITY_THRESHOLD` and the regeneration loop; `caption_similarity` telemetry keeps its event name and reports the selector's scores
- History depth 30 for selection on both web and cron; openings-to-avoid from the last two
- Condense pass on the selected candidate only
- Model trial: two nightly runs (current model and the #182 model) on the same 20 analyses; blind reading by the owner; switch in the orchestrator payload if it wins

**Out of scope:**
- Prompt wording (PUB-051)
- Embedding-based similarity (a later item if TF-IDF proves insufficient)

## Acceptance Criteria

- AC1: Given a fake client returning three candidates of which one is a clone of history, when selection runs, then the clone is never chosen
- AC2: Given a run, when the fake client's calls are counted, then one caption request was made (not two) and the happy path does not exceed two OpenAI calls per image plus the optional condense
- AC3: Given a fixed seed, when selection runs twice on the same candidates, then the same winner is chosen
- AC4: Given selection completes, when logs are inspected, then `caption_candidate_selected` carries per-candidate scores and the winner's index
- AC5: Given the codebase, when it is searched, then `CAPTION_SIMILARITY_THRESHOLD` and the trigram regeneration loop no longer exist
- AC6: Given the real web service and the real orchestrator with a fake store, when each fetches history, then both fetch the same depth
- AC7: Given the PUB-049 harness, when the PR body is written, then TF-IDF cosine to history drops against the PUB-051 result and tells rate does not rise
- AC8: Given two nightly snapshots (current model, trial model), when the owner reads them blind, then the reading and the score tables are recorded on the trial issue and the decision is made from both
- AC9: Given this item ships, when its implementing PR merges, then #193 and #195 are closed by that PR (`Closes #193`, `Closes #195` in its body) with the evidence, and #182 is closed once the trial model and budget it asks for are recorded in this spec

## Implementation Notes

- Two sub-issues: #193 (selector) and #195 (model trial, owner-assigned, no code).
- Weighting suggestion: `score = tells_rate * 2 + cosine_to_history`; lowest wins. Make the weights settings so the harness can sweep them.
- Keep `trigram_jaccard` only if the metrics module still uses it; otherwise delete with its tests.

## Risks

- Three candidates triple caption-completion tokens; at gpt-4o-mini prices this is cents per run. The trial model may cost more; #182 sets the budget.
- Selecting for distance from history can drift toward oddness; the tells term and the owner's reading are the counterweight.

## Success Metrics

- Harness cosine-to-history below the PUB-051 result on every nightly run for two weeks.
- Owner's blind reading prefers the selected output.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issues [#193](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/193), [#195](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/195), [#182](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/182)
- [PUB-040: OpenAI Model Lifecycle Warnings](archive/PUB-040_model-lifecycle-warnings.md) — the model config this trial uses
- Prior fixes #82 (similarity gate), #144 (telemetry gate)

## Change Log

- 2026-09-27 — Post-PUB-051 refresh: updated Status to Not Started (both dependencies now Done), refreshed Problem section with post-PUB-051 function names (`pick_content_angle` replaces `pick_structure_directive`, `CONTENT_ANGLES` replaces `STRUCTURE_DIRECTIVES`), updated line references to match current `ai.py` layout, noted that both web and cron now use `angle_history_depth(window_size)` but text window is still 3.
- 2026-09-27 — Issue-closing contract: added an AC naming every GitHub issue this item closes (implementing PR carries `Closes #N`), so no issue is left stale.
