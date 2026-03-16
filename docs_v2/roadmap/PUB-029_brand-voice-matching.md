# PUB-029: Brand Voice Matching

| Field | Value |
|-------|-------|
| **ID** | PUB-029 |
| **Category** | AI |
| **Priority** | P2 |
| **Effort** | S–M |
| **Status** | Not Started |
| **Dependencies** | PUB-025 |

## Problem

AI-generated captions sound generic. Every publisher instance produces captions in the same "AI copywriter" voice regardless of the creator's personality, audience, or brand. In 2026, audiences can spot AI-generated text instantly, and generic captions actively hurt engagement. The winning approach is few-shot voice matching: give the AI examples of the creator's real captions, and it rewrites to match their tone, vocabulary, and style.

Our system already supports per-tenant prompt overrides (`system_prompt`, `role_prompt` via orchestrator config), but these require manual prompt engineering. Users don't write prompts — they write captions.

## Desired Outcome

Users provide 5-10 example captions that represent their voice. The AI uses these as few-shot examples when generating captions, producing output that matches the creator's tone, vocabulary, sentence structure, and personality. No prompt engineering required — just paste your best captions and the AI learns your style.

## Scope

- New `voice_profile` config block: a list of example captions (strings) per tenant
- Voice profile storage: orchestrator config (per-instance) or a dedicated field in tenant settings
- Caption generation prompt updated to include few-shot examples from the voice profile
- Voice profile applies to all platform-specific captions (PUB-025) while respecting each platform's constraints
- Web UI: voice profile management (view, add, remove example captions) in settings/config section
- Feature flag: `features.voice_matching_enabled` (default `false`); when disabled, captions use default AI style
- Fallback: if voice profile is empty or feature is disabled, behavior is identical to today

## Non-Goals

- No automated voice profile extraction from existing posts (scraping the user's social media history)
- No voice profile training or fine-tuning of models
- No per-platform voice profiles (one voice applies across all platforms; platform adaptation from PUB-025 handles tone differences)
- No voice consistency scoring or feedback loop

## Acceptance Criteria

- AC1: A `voice_profile` config field accepts a list of 1-20 example caption strings per tenant
- AC2: When voice matching is enabled and a voice profile exists, example captions are included as few-shot context in the caption generation prompt
- AC3: Generated captions demonstrably reflect the tone, vocabulary, and style of the provided examples
- AC4: Voice matching works with platform-adaptive captions (PUB-025): each platform's caption matches the voice while respecting platform constraints
- AC5: When the voice profile is empty or `features.voice_matching_enabled` is false, caption generation is identical to current behavior
- AC6: Voice profile is configurable via orchestrator config (per-instance) and standalone INI config
- AC7: Web UI settings page allows viewing and editing the voice profile (add/remove example captions)
- AC8: The few-shot examples do not exceed a configurable token budget (default 500 tokens) to control API costs
- AC9: Preview mode displays generated captions with voice matching applied
- AC10: Voice profile content is not logged (may contain personal/sensitive text)

## Implementation Notes

- Few-shot prompting: include examples in the system or user message as "Here are examples of captions in the creator's voice:" followed by the examples, then "Generate a caption in this same voice for the following image:"
- Token budget: if examples exceed the budget, select a representative subset (most recent or most diverse)
- Orchestrator config shape: `content.voice_profile: ["example caption 1", "example caption 2", ...]`
- INI config: `[Content]` section with `voice_examples` as a JSON-encoded list or one-per-line format
- Web UI: simple textarea-based editor in the config/settings section; each line or entry is one example
- The voice profile should be treated as user content — sanitize for prompt injection but preserve the user's actual words
- Prompt injection defense: voice examples are wrapped in clear delimiters and the system prompt explicitly instructs the model to treat them as style references only, not as instructions

## Related

- [PUB-025: Platform-Adaptive Captions](PUB-025_platform-adaptive-captions.md) — the per-platform caption system this enhances with voice consistency
- [PUB-001: Caption File](archive/PUB-001_caption-file.md) — original caption generation system
