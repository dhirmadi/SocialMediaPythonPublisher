# PUB-050: Owner Voice Corpus in Every Caption Prompt

| Field | Value |
|-------|-------|
| **ID** | PUB-050 |
| **Category** | AI |
| **Priority** | P0 |
| **Effort** | S |
| **Status** | Proposal |
| **Dependencies** | PUB-049 |

## User Story

As a publisher operator curating content, I want the captions the model writes to be anchored on captions I actually wrote, so that "in the account owner's voice" means something and the output stops reading like the average of every warm fine-art caption on the internet.

## Problem

`voice_profile` defaults to `None` on both loaders (`config/loader.py:289-290`, `config/orchestrator_models.py:181`), and `voice_matching_enabled` is derived from its presence (`config/schema.py:460-481`, #131), so voice matching is off by default. The only setter, `POST /api/config/voice-profile` (`web/app.py:867-878`), is documented as "in-memory for this process; does not persist back to the orchestrator". The cron publisher is a different process and never sees examples. When a profile does exist, `build_voice_examples_block` (`services/ai.py:832-852`) renders the same examples in the same order in every call, which is a template rather than a voice. The rendered default prompt says "You write in the account owner's voice; adult, warm, specific, unhurried" and supplies nothing about that voice. The review names this the most likely single root cause of "AI-like" captions.

## Desired Outcome

Every cron and web caption prompt for the tenant contains four to six owner-written examples, sampled per image from a durable corpus of ten to twenty, stable per image and varied across images. The web setter states honestly that it is process-local, or persists through the orchestrator if a write endpoint exists.

## Scope

**In scope:**
- Orchestrator (contract owner, separate PR there): populate `content.voice_profile` for the tenant from the corpus supplied in #179, tagged by platform if the schema allows
- `build_voice_examples_block`: sample 4 to 6 examples seeded by the image content hash, within the existing 500-token budget, preferring examples tagged for the platform being written
- Web setter response and UI carry `persisted: false` and name the orchestrator field, or persist through the orchestrator
- `docs_v2/07_AI/AI_PROMPTS_AND_MODELS.md` documents the field, the sampling and where to set it

**Out of scope:**
- Prompt wording, directives, sampling parameters (PUB-051)
- Candidate selection (PUB-052)
- Writing the corpus (owner, #179)

## Acceptance Criteria

- AC1: Given a 12-item profile and an image hash, when the prompt is rendered, then it contains between four and six examples
- AC2: Given the same image hash twice, when the prompt is rendered, then the same examples appear; given a different hash, a different sample appears
- AC3: Given examples tagged by platform, when the email prompt is rendered, then email-tagged examples are preferred
- AC4: Given a runtime payload with `content.voice_profile` set, when a workflow run executes through the real `OrchestratorConfigSource` and `WorkflowOrchestrator` with a fake OpenAI client, then the recorded caption prompt contains the sampled block
- AC5: Given the web setter is called, when the response is inspected, then it carries `persisted: false` (or the orchestrator write succeeded and the response says so)
- AC6: Given the PUB-049 harness, when the PR body is written, then it contains the offline score table before and after

## Implementation Notes

- Sub-issue #190. Depends on #179 (corpus) and #189 (harness).
- Order: orchestrator PR first, then this one; the Publisher PR body links the orchestrator PR.
- Seed: `int.from_bytes(sha256[:8])` over the content hash; deterministic and cheap.

## Risks

- A corpus that is too small or too uniform anchors as hard as the old static examples did; #179 asks for at least three per platform and two deliberately plain ones.

## Success Metrics

- Harness TF-IDF cosine to history and tells rate both improve against the PUB-049 baseline in the PR body.
- The owner's blind reading in PUB-052 prefers the post-corpus output.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issues [#190](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/190), [#179](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/179)
- [PUB-029: Brand Voice Matching](archive/PUB-029_brand-voice-matching.md) — introduced `voice_profile`
- [PUB-039: AI Caption Feature Flags & Voice Profile](archive/PUB-039_ai-caption-feature-flags.md) — the orchestrator field
- Prior fix #131 (voice matching default)
