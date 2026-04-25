# PUB-029: Brand Voice Matching

| Field | Value |
|-------|-------|
| **ID** | PUB-029 |
| **Category** | AI |
| **Priority** | P2 |
| **Effort** | S–M |
| **Status** | Not Started |
| **Dependencies** | PUB-025 (Done), PUB-039 (Partially covers config + flag) |

## Problem

AI-generated captions sound generic. Every publisher instance produces captions in the same "AI copywriter" voice regardless of the creator's personality, audience, or brand. In 2026, audiences can spot AI-generated text instantly, and generic captions actively hurt engagement. The winning approach is few-shot voice matching: give the AI examples of the creator's real captions, and it rewrites to match their tone, vocabulary, and style.

Our system already supports per-tenant prompt overrides (`system_prompt`, `role_prompt` via orchestrator config), but these require manual prompt engineering. Users don't write prompts — they write captions.

## Desired Outcome

Users provide 5-10 example captions that represent their voice. The AI uses these as few-shot examples when generating captions, producing output that matches the creator's tone, vocabulary, sentence structure, and personality. No prompt engineering required — just paste your best captions and the AI learns your style.

## Scope

This item is the *remaining work* to complete the brand voice feature end-to-end.

**Already shipped (PUB-039):**
- `content.voice_profile: list[str] | None` (1–20 examples) exists in config models and loaders
- `features.voice_matching_enabled` exists (default `false`)
- Voice examples are prepended to `CaptionSpec.examples` when enabled (so they flow into caption prompts)
- `voice_profile` is redacted from config logging

**In scope for PUB-029:**
- **Token budget enforcement** for voice examples in prompts (default 500 “rough tokens” budget)
- **Prompt injection hardening**: wrap voice examples in clear delimiters + explicit “examples are style only” instruction
- **Standalone INI support** for `voice_profile` (INI fallback path) in addition to orchestrator/env JSON
- **Web UI settings editor** for viewing/editing `voice_profile` (simple textarea UX)

## Non-Goals

- No automated voice profile extraction from existing posts (scraping the user's social media history)
- No voice profile training or fine-tuning of models
- No per-platform voice profiles (one voice applies across all platforms; platform adaptation from PUB-025 handles tone differences)
- No voice consistency scoring or feedback loop

## Acceptance Criteria

### Shipped (documented for completeness)

- AC-00a (Shipped): `content.voice_profile` accepts 1–20 non-empty strings.
- AC-00b (Shipped): `features.voice_matching_enabled` gates whether voice examples are prepended into caption generation context.
- AC-00c (Shipped): `voice_profile` is redacted from config logging.

### To deliver in PUB-029

- AC-01: **Token budget**: when voice matching is enabled, the set of voice examples included in prompts is truncated to fit a configurable budget (default 500 rough tokens ≈ 2000 chars). Truncation is deterministic and stable (preserve original ordering; drop items from the end).
- AC-02: **Prompt injection hardening**: voice examples are wrapped in explicit delimiters and preceded by an instruction that they are *style references only* and must not be treated as instructions.
- AC-03: **Platform-adaptive compatibility**: voice matching continues to work with PUB-025 multi-platform captions (no breakage; examples still flow to each platform block).
- AC-04: **Feature-off compatibility**: when `voice_matching_enabled=False` or `voice_profile` is empty/None, the prompt content is identical to current behavior (no “voice examples” block).
- AC-05: **INI fallback support**: INI `[Content]` supports specifying `voice_profile` as a JSON list string (e.g., `voice_profile = ["ex1","ex2"]`). Invalid JSON is a configuration error; missing key behaves as None.
- AC-06: **Web UI editor**: admin-only settings UI supports viewing + editing the voice profile as a textarea. Saving updates runtime config in-memory for the tenant/session (no orchestrator writeback in this item).
- AC-07: **Preview mode**: preview output indicates whether voice matching is enabled and (if enabled) how many voice examples were applied after token-budget truncation (but does not print the examples themselves).

## Implementation Notes

- **Few-shot prompting shape**: add a “voice examples” block *only* when enabled and examples remain after truncation:
  - Header line explaining these are style references only
  - Start/end delimiters
  - One example per line with numbering
- **Token budget heuristic**: use existing “rough token estimate” convention (1 token ≈ 4 chars). Default budget 500 tokens ⇒ ~2000 chars. Truncate deterministically by preserving order and dropping from the end until within budget.
- **Orchestrator config shape** (already supported): `content.voice_profile: ["example caption 1", "example caption 2", ...]`
- **INI config**: support `voice_profile` as JSON list string in `[Content]`. (One-per-line format is out of scope.)
- **Web UI**: keep it simple (textarea, one example per line). This item does not persist back to orchestrator; it is a runtime/session convenience only.

## Related

- [PUB-025: Platform-Adaptive Captions](PUB-025_platform-adaptive-captions.md) — the per-platform caption system this enhances with voice consistency
- [PUB-001: Caption File](archive/PUB-001_caption-file.md) — original caption generation system
