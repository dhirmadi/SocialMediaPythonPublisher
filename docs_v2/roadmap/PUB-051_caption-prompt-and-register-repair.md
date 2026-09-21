# PUB-051: Caption Prompt and Register Repair

| Field | Value |
|-------|-------|
| **ID** | PUB-051 |
| **Category** | AI |
| **Priority** | P0 |
| **Effort** | M |
| **Status** | Proposal |
| **Dependencies** | PUB-049 |

## User Story

As a publisher operator curating content, I want the caption prompt to vary what it asks for, stop re-inviting the shapes it was meant to remove, and give each platform a stance rather than a list of adjectives, so that captions differ from one another in the ways a reader notices.

## Problem

All verified by running the real prompt builder with a fake client (review [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177), captions H2, M1, M2, M3):

1. **The structure-directive rotation has one state.** `utils/captions.py:329-348` `classify_caption_structure` maps any two-sentence caption without `?` to `observation` and can only return `declarative` for a single sentence of eight or more words, so `pick_structure_directive` (`:351-369`) returns "Open with a plain declarative statement." on every run, for every platform, including the regeneration retry.
2. **The closing-avoid line is counterproductive.** `caption_closing_pattern` (`:377-384`) classifies a plain sentence as `statement`; the rendered constraint then says "avoid: statement", and the natural alternative for a 30-word email subject is the question #138 removed. With `closing: any` the line is always emitted.
3. **The prompt is 8:1 instruction to output.** With history and a profile the user message is about 1,180 tokens: 24 quoted "openings to avoid" in the house register, "Use DIFFERENT openings" three times while every platform gets the same directive, and about 460 tokens of analysis rendered as Python repr with hex colours and 15 to 25 snake_case tags (`build_analysis_context`, `services/ai.py:606-666`) against about 40 tokens of persona.
4. **The SD prompt shares the completion.** `generate_multi_with_sd` (`ai.py:1354-1405`) produces every caption and `sd_caption` in one JSON object; the prompt-engineer brief pulls diction toward its nouns.
5. **Sampling.** Temperature 0.7, presence 0.6, no frequency penalty (`ai.py:101-104`). Presence acts within a completion, not across runs.
6. **The vision register pins the vocabulary.** `ai_prompts.yaml:1-5` makes the vision model a "neutral analyst"; `:33-35` briefs the caption-facing `sensory_detail` with five fixed nouns (texture, tension, temperature, gaze, breath) at temperature 0.4. The in-code default that tried to state both registers (`ai.py:191-233`) is dead because the YAML wins (`:448`).
7. **Email has no register after #138**, and telegram's "conversational, emoji-friendly, artistic commentary" is the register of the tells. `caption_history` records rows for platforms that failed (`core/workflow.py:772-783`), and a partial retry re-pays vision and caption instead of reading the sidecar it wrote.

## Desired Outcome

Exactly one content angle per platform per call, rotating across runs from an explicit stored column. No closing-pattern constraint. A caption user message under 500 tokens with history and a six-example profile, with the analysis as a short prose paragraph after the brief. Captions and the SD prompt in separate completions. Caption-facing vision fields produced under the owner persona with a rotating senses pool. Each platform brief names who is speaking to whom. History records only published captions; a partial retry costs zero OpenAI calls when the sidecar holds the captions.

## Scope

**In scope:**
- Replace `STRUCTURE_DIRECTIVES` with a content-angle pool rotated by an `angle` column stored with each caption (additive migration); delete `classify_caption_structure`
- Delete the closing-pattern constraint; openings-to-avoid cut to the last two; emoji and hashtags stripped from history before deriving constraints
- Analysis rendered as prose after the brief, capped at about 120 tokens; `color_palette`, `tags`, `aesthetic_terms` dropped from the caption prompt
- `sd_caption` moved into the vision call; caption completion keys are platforms only
- Caption call `temperature=0.9`, `frequency_penalty=0.3`, `presence_penalty=0.6`
- `caption.rules` extended with the measured tells as positive replacements; default persona rewritten as a person; rope-specific persona moved to the tenant `system_prompt` example in docs
- Vision: second small call for `sensory_detail` and `mood_note` under the owner persona at temperature 0.9 with a rotating senses pool (or a two-register system prompt; the PR states the choice and cost); dead `_DEFAULT_VISION_*` constants removed or made the real fallback
- Platform stances in the YAML `style`; history saved only for published platforms; retry reuses `caption_generated` from the sidecar; a non-JSON vision reply retried once before the expensive fallback

**Out of scope:**
- Candidate generation and selection (PUB-052)
- Voice corpus plumbing (PUB-050)
- Any platform limit change

## Acceptance Criteria

- AC1: Given realistic history, when the prompt is rendered three times, then each platform receives exactly one angle per call and the angle differs across the three runs; the regeneration path picks a different angle from the rejected draft
- AC2: Given any history, when the prompt is rendered, then no "closing pattern" line is present and at most two openings-to-avoid appear per platform
- AC3: Given history and a six-example profile, when the prompt is rendered, then the user message is under 500 tokens and contains no hex colour or snake_case tag
- AC4: Given the caption call, when the fake client records the request, then `response_format` keys are the enabled platforms only and `temperature`, `frequency_penalty` and `presence_penalty` equal the configured values
- AC5: Given the vision stage, when the fake client records the requests, then `sd_caption` comes from the vision call and is written to the sidecar unchanged, and the caption-facing fields come from a call whose system message is the owner persona
- AC6: Given two images, when the senses pool is rendered, then the pools differ by seed; given the sidecar phase-2 metadata, then the caption-facing fields are absent
- AC7: Given a partial publish followed by a retry through the real orchestrator with fake publishers, when both runs complete, then vision and caption fakes were called once in total and `caption_history` holds one row per successfully published platform
- AC8: Given a vision reply that is not JSON, when the analyzer runs, then it is retried once at the same resolution before the fallback
- AC9: Given the PUB-049 harness, when the PR body is written, then opener share and tells rate improve against the baseline and TF-IDF cosine to history does not rise

## Implementation Notes

- Three sub-issues, three PRs: #191 (prompt and sampling), #192 (vision register), #194 (stances, history, retries). Each carries the harness table.
- Tests assert structure (angle count, line absence, token bound, JSON keys, call sequence), not wording; this starts the PUB-060 rewrite of the 59 substring tests.
- The `angle` column is an additive migration; list it in the PR body.

## Risks

- Temperature 0.9 raises overshoot on the 240-character email subject; the condense pass guards length, and AC9 catches a tells regression.
- Moving `sd_caption` to the vision call changes which model writes it (gpt-4o instead of gpt-4o-mini); slightly higher cost, better SD prompts. State it in the PR.

## Success Metrics

- Harness: max opener share under 30%, tells rate halved against baseline, angle distribution roughly uniform over 20 images.
- Owner's reading in PUB-052 prefers the repaired output.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issues [#191](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/191), [#192](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/192), [#194](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/194)
- [PUB-025: Platform-Adaptive Captions](archive/PUB-025_platform-adaptive-captions.md), [PUB-035: Caption Context Intelligence](archive/PUB-035_caption-context-intelligence.md), [PUB-041: Vision Cost Optimization & Richer Caption Inputs](archive/PUB-041_vision-cost-optimization.md), [PUB-046: Email Caption Length Control](archive/PUB-046_email-caption-length-control.md)
- Prior fixes #79, #81, #82, #138; open [#171](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/171) (dead sanitizer default) closes here
