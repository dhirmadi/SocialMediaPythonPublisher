# PUB-052: Caption Candidate Selection and Model Trial

| Field | Value |
|-------|-------|
| **ID** | PUB-052 |
| **Category** | AI |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Proposal |
| **Dependencies** | PUB-049, PUB-051 |

## User Story

As a publisher operator curating content, I want the pipeline to generate a few candidate captions and keep the one least like what was posted recently and least like a machine, so that diversity is something the system does on every run rather than a gate that never fires.

## Problem

`services/ai.py:1492-1622` generates once, scores each platform against history with trigram Jaccard, and regenerates with a diversity clause if any score exceeds 0.45. PUB-049 establishes that the metric scores real clones at 0.04, so the gate fires only on near-verbatim reuse, which a 0.7-temperature model essentially never produces; the `caption_similarity` telemetry (`:1610-1618`) reports comfortable diversity forever, and when the gate does fire the regeneration re-picks the same stuck directive. Web fetches 8 history items per platform (`web/service.py:878`), cron fetches 3 (`core/workflow.py:551`). Separately, `caption_model` is gpt-4o-mini (`config/schema.py:85`), the cheapest 2024 model; the name validator now accepts any model (#81), so a trial is a config change, but done before the pipeline is repaired a better model would hide whether the pipeline improved.

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
