# PUB-064: Make the Caption Harness Exercise the Voice Path

| Field | Value |
|-------|-------|
| **ID** | PUB-064 |
| **Category** | AI |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Proposal |
| **Dependencies** | PUB-049, PUB-050 |

## User Story

As a publisher operator judging whether the owner-voice corpus actually improved captions, I want the offline harness to generate the way production generates, so that a before/after score table measures the change I shipped instead of a code path nobody runs.

## Problem

The PUB-049 harness cannot observe PUB-050 at all. Two independent places drop the voice examples:

- `scripts/caption_eval.py:429` calls `create_multi_caption_pair_from_analysis(analysis, specs, history=history)` with **no `voice_examples` argument**, so the parameter defaults to `None`.
- `scripts/caption_eval.py:164-177` (`build_specs`) hand-builds each `CaptionSpec(..., examples=(), ...)` rather than going through `CaptionSpec.for_platforms(config)`. Its own docstring says "`examples` — empty: a tenant with no voice profile".

`_build_multi_prompt` (`services/ai.py`) promotes `spec.examples` only when `voice_examples is None`, and those are `()`, so `block_examples` is empty and **no STYLE REFERENCES block is emitted at all** — before or after PUB-050.

The consequence is that PUB-050's AC6 ("the PR body contains that offline score table") is not blocked on sequencing, as its spec assumed, but is unsatisfiable by construction: a `--nightly` run before and after the sampling change produces a **structurally guaranteed zero delta**, for any corpus. PUB-050 shipped with AC6 open and this recorded in its summary. PUB-052's blind reading inherits the same blindness — its Success Metrics compare against a harness baseline that cannot see the feature under test.

## Desired Outcome

A `--nightly` run generates captions carrying a sampled STYLE REFERENCES block, exactly as `core/workflow.py` does, so the harness's TF-IDF-cosine and tells-rate metrics respond to a change in the corpus or in the sampler.

## Scope

**In scope:**
- `scripts/caption_eval.py`: a fixture voice profile (checked in beside the existing analyses/history fixtures), and passing `sample_voice_examples(...)` into `create_multi_caption_pair_from_analysis` with a per-fixture seed, mirroring `core/workflow.py`'s call.
- Regenerating `snapshot.json` and `caption_eval_thresholds.json`, in the separate, deliberate step PUB-049 already defines for that (`--nightly`, then `--generate-thresholds`). PUB-049's own Scope requires these never be regenerated in the same PR as a snapshot change — honour that split here too.
- A note in PUB-049's archived spec and in `docs_v2/07_AI/AI_PROMPTS_AND_MODELS.md` §8.1 recording that the harness now covers the voice path.

**Out of scope:**
- Writing the real owner corpus (#179) — the fixture profile here is harness scaffolding, deliberately *not* the owner's voice, so a corpus edit never silently moves the CI bars.
- Changing the metrics, thresholds policy or the sampler itself.
- Retro-satisfying PUB-050's AC6. That item is merged and archived; this one supersedes the gate. See Related.

## Acceptance Criteria

- AC1: Given the fixture voice profile and a fixture analysis, when `scripts/caption_eval.py --nightly` builds a prompt, then that prompt contains a `BEGIN VOICE EXAMPLES` / `END VOICE EXAMPLES` block whose entries are exactly what `sample_voice_examples(...)` returns for that fixture's seed.
- AC2: Given the same fixture run twice, when the prompts are compared, then the voice block is identical both times — the harness seeds per fixture, not per run, so a snapshot diff never churns on sampling alone.
- AC3: Given two fixtures with different seeds, when their prompts are compared, then their voice blocks differ, proving the harness exercises per-image variation rather than one fixed block.
- AC4: Given `--offline`, when it runs, then it still makes zero network calls and completes in under ten seconds (PUB-049 AC3 must not regress).
- AC5: Given the sampler is reverted to the pre-PUB-050 flat `truncate_voice_profile_to_budget(...)`, when `--nightly` regenerates and scores, then at least one metric moves — i.e. the harness can now detect the class of change PUB-050 made. This is the acceptance criterion that the whole item exists for; verify it explicitly rather than assuming.

## Implementation Notes

- Mirror `core/workflow.py`'s call shape rather than inventing one, so the harness keeps measuring what production does: `sample_voice_examples(profile, seed_source=<fixture content hash>, platform_tags=..., platforms=list(specs.keys()))`.
- The fixture profile should be short entries (under ~300 characters) so the 500-token budget never truncates and the harness measures sampling, not degradation. See `AI_PROMPTS_AND_MODELS.md` §8.1 for the measured thresholds.
- Consider whether `build_specs` should simply call `CaptionSpec.for_platforms(config)`. It would remove the duplicated spec construction, but pulls tenant config into the harness — weigh it, and record the choice in the summary.
- Regenerating the snapshot changes the committed baseline, so the PR must show the before/after score table in its body; that is the evidence this item worked.

## Risks

- A fixture voice profile that is too distinctive will dominate the metrics and mask real regressions. Keep it plain and generic; it is scaffolding, not a voice.
- Regenerating thresholds off a single run bakes in that run's variance. PUB-049's Risks already note a three-run average as the fast-follow; the same caveat applies.

## Success Metrics

- Reverting the sampler moves a metric (AC5) — the harness is no longer blind to prompt-input changes.
- PUB-052's blind reading can be compared against a harness number that responds to the corpus.

## Related

- [PUB-049: Caption Evaluation Harness](archive/PUB-049_caption-evaluation-harness.md) — built the harness this item extends
- [PUB-050: Owner Voice Corpus in Every Caption Prompt](archive/PUB-050_owner-voice-corpus.md) — shipped with AC6 open; this item is why it could not be closed, and supersedes that gate
- PUB-052: Caption Candidate Selection — inherits the same measurement blindness until this lands
- Corpus authoring is [#179](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/179), owner-authored content, not code

## Change Log

- 2026-09-26 — Created while closing out PUB-050. The gap was found by an adversarial review pass and confirmed independently three times against `scripts/caption_eval.py:429` and `:164-177`.
