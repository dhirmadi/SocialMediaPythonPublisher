# Implementation Handoff: PUB-046 — Email Caption Length Control

**Hardened:** 2025-05-13
**Status:** Ready for implementation

## For Claude Code

### Summary

Fix FetLife email caption generation to stay within the 240-character limit without awkward truncation. Six parts: (A) few-shot examples in config, (B) word-count prompt instructions, (C) `max_tokens` ceiling, (D) AI condense pass on overshoot, (E) temperature reduction, (F) tenant prompt docs. All changes scoped to short-limit platforms (`max_length <= 300`) to avoid regression on telegram/instagram.

### Test-first targets

| AC | Test file | Key test cases |
|----|-----------|----------------|
| AC-01 | `tests/test_ai_email_length_control.py` | Assert email config in static YAML has ≥3 examples (each ≤240 chars) and non-empty guidance with "word" in it |
| AC-02 | `tests/test_ai_email_length_control.py` | `build_platform_block` with `max_length=240` → output contains "words"; `max_length=4096` → output contains "chars" |
| AC-03 | `tests/test_ai_email_length_control.py` | Assert email style in loaded static config contains "sentence" and "question" |
| AC-04 | `tests/test_ai_email_length_control.py` | Mock `_FakeCompletions`; call `generate` with email spec (240) → captured kwargs has `max_tokens=80`. Call with telegram spec (4096) → no `max_tokens` in kwargs |
| AC-05 | `tests/test_ai_email_length_control.py` | Mock `_FakeCompletions`; call `generate_multi` with email+telegram specs → `max_tokens=512`. Call with telegram-only → no `max_tokens` |
| AC-06 | `tests/test_ai_email_length_control.py` | Call `generate` with email spec → `temperature=0.5`. Call with telegram spec → `temperature=0.7`. Call `generate_multi` with mixed specs → `temperature=0.5` |
| AC-07 | `tests/test_ai_email_length_control.py` | Mock OpenAI to return 300-char email caption; mock `_condense_caption` to return 200-char version → result is the condensed version. Mock condense to return 280-char version → result is `smart_truncate(original)` |
| AC-08 | `tests/test_ai_email_length_control.py` | Mock `_condense_caption` to raise `Exception` → result is `smart_truncate(original)`, no exception propagated |
| AC-09 | `tests/test_ai_email_length_control.py` | Use `caplog` fixture; trigger condense happy path → assert `caption_condensed` log with required fields. Trigger condense failure → assert `caption_condense_failed` log |
| AC-10 | `tests/test_ai_email_length_control.py` | Call `generate` with telegram spec (4096) → verify `temperature=0.7`, no `max_tokens`. Call `generate_multi` with telegram+instagram only → same |
| AC-11 | `tests/test_ai_multi_caption.py` | Update `test_email_style_in_prompt` to assert new email style text (expected change, not a regression) |
| AC-12 | — | Documentation only — Part F section in the spec serves as the deliverable |

### Mock boundaries

| External service | Mock strategy | Existing pattern |
|-----------------|---------------|------------------|
| OpenAI (caption generation) | `_FakeCompletions` / `_FakeClient` with `monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", ...)` | `tests/test_ai_multi_caption.py` lines 33–48 |
| OpenAI (condense call) | Same `_FakeCompletions` but needs to return a **second** response for the condense call. Use a `_FakeCompletions` variant that returns different responses per call (e.g. list of responses, pop from front). | New — extend `_FakeCompletions` to support multiple response contents |
| Static config | `get_static_config()` — typically auto-loaded from YAML. For unit tests asserting config values, call it directly. For prompt tests, the config is already loaded by the production code. | `tests/test_captions_platform_limits_static.py` |
| Rate limiter | For condense-path tests, the condense call goes through the same `_rate_limiter`. In unit tests of `CaptionGeneratorOpenAI` directly (not via `AIService`), the rate limiter is not involved. | N/A — generator methods don't use rate limiter directly |

### Files likely touched

| Area | Files to modify | Files to create |
|------|-----------------|-----------------|
| Config | `publisher_v2/src/publisher_v2/config/static/ai_prompts.yaml` | — |
| AI service | `publisher_v2/src/publisher_v2/services/ai.py` | — |
| Tests | `publisher_v2/tests/test_ai_multi_caption.py` (update 1 assertion) | `publisher_v2/tests/test_ai_email_length_control.py` |

### Implementation order (recommended)

1. **Part A** — Update `ai_prompts.yaml` (config change, no code). Write AC-01, AC-03 tests first.
2. **Part B** — Update `build_platform_block` and `generate`'s length_instruction for word-count. Write AC-02 test first.
3. **Part C** — Add `max_tokens` logic to all 4 caption methods. Write AC-04, AC-05 tests first.
4. **Part E** — Add temperature selection logic. Write AC-06 test first. (E before D because E is simpler.)
5. **Part D** — Add `_condense_caption` method; update `_parse_platform_captions` (convert from `@staticmethod` to regular method); update `generate` and `generate_with_sd`. Write AC-07, AC-08, AC-09 tests first.
6. **Part F** — Already in the spec; AC-12 is satisfied by the spec content.
7. **Regression** — Run full suite, update `test_email_style_in_prompt`, verify AC-10, AC-11.

### Key design decisions (pre-made)

| Decision | Resolution |
|----------|-----------|
| Where does condense logic live? | New method `CaptionGeneratorOpenAI._condense_caption(caption, max_length, platform)` |
| `_parse_platform_captions` is currently `@staticmethod` — how to call condense? | Convert to regular method (needs `self` for OpenAI client access) |
| What temperature for condense? | `0.3` — low variance, predictable shortening |
| What if condense fails? | Catch all exceptions, log `caption_condense_failed`, return original (let `smart_truncate` handle it) |
| Short-limit threshold | Named constant `SHORT_LIMIT_THRESHOLD = 300` at module level |
| Multi-platform max_tokens | Fixed at `512` when any spec is short-limit (generous to avoid clipping long-form captions) |

### Non-negotiables for this item

- [ ] Preview mode: N/A — caption generation runs the same in preview and production (the condense pass is an OpenAI call, same as the primary caption call — side-effect-free)
- [ ] Secrets: N/A — no new secrets; uses existing OpenAI API key
- [ ] Auth: N/A — no web endpoint changes
- [ ] Async hygiene: `_condense_caption` is `async` (OpenAI call). All existing caption methods are already async. No blocking work introduced.
- [ ] Coverage: ≥80% on `services/ai.py` affected code paths

### Known pitfall

The `_FakeCompletions` mock in existing tests (`test_ai_multi_caption.py`) returns a single fixed response. For condense-path tests, you need a version that can return **different responses per call** (first call = oversized caption, second call = condensed caption). Build a `_SequentialFakeCompletions` that pops from a response list, or use `unittest.mock.AsyncMock` with `side_effect`.

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-046_email-caption-length-control.md
```
