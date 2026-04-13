# Implementation Handoff: PUB-025 — Platform-Adaptive Captions

**Hardened:** 2026-03-16
**Status:** Ready for implementation

## For Claude Code

### Test-first targets

| AC | Test file | Key test cases |
|----|-----------|----------------|
| AC1 | `publisher_v2/tests/test_ai_multi_caption.py` | `test_generate_multi_returns_dict_per_platform`, `test_single_openai_call` |
| AC2 | `publisher_v2/tests/test_ai_multi_caption.py` | `test_caption_truncated_when_exceeds_max_length` |
| AC3 | `publisher_v2/tests/test_ai_multi_caption.py` | `test_missing_platform_key_raises_error` |
| AC4 | `publisher_v2/tests/test_ai_multi_caption.py` | `test_uses_json_response_format` |
| AC5-7 | `publisher_v2/tests/test_ai_multi_caption.py` | `test_telegram_style_in_prompt`, `test_instagram_style_in_prompt`, `test_email_style_in_prompt` (verify prompt includes correct style directive per platform) |
| AC8 | `publisher_v2/tests/test_ai_multi_caption.py` | `test_platform_styles_loaded_from_yaml` |
| AC9 | `publisher_v2/tests/test_workflow_multi_caption.py` | `test_each_publisher_receives_own_caption` |
| AC10 | `publisher_v2/tests/test_workflow_multi_caption.py` | `test_format_caption_still_applied_as_safety_net` |
| AC11 | `publisher_v2/tests/test_workflow_multi_caption.py` | `test_caption_override_applies_to_all_publishers` |
| AC12 | `publisher_v2/tests/test_workflow_multi_caption.py` | `test_single_publisher_generates_single_caption` |
| AC13 | `publisher_v2/tests/test_ai_multi_caption.py` | `test_generate_multi_with_sd_returns_captions_plus_sd` |
| AC14 | `publisher_v2/tests/test_ai_multi_caption.py` | `test_sd_caption_format_unchanged` |
| AC15 | `publisher_v2/tests/test_ai_multi_caption.py` | `test_sd_fallback_to_generate_multi` |
| AC16 | `publisher_v2/tests/test_caption_spec.py` | `test_for_platforms_returns_enabled_only`, `test_for_platforms_filters_disabled` |
| AC17 | `publisher_v2/tests/test_caption_spec.py` | `test_for_config_still_works_deprecated` |
| AC18 | `publisher_v2/tests/test_preview_multi_caption.py` | `test_preview_shows_per_platform_captions` |
| AC19 | `publisher_v2/tests/test_web_multi_caption.py` | `test_analysis_response_includes_platform_captions` |
| AC20 | (quality gate) | `uv run ruff check .` + `uv run mypy . --ignore-missing-imports` |
| AC21 | All above | Aggregate pass |

### Mock boundaries

| External service | Mock strategy | Existing fixture |
|-----------------|---------------|------------------|
| OpenAI chat completions | `unittest.mock.AsyncMock` on `client.chat.completions.create` | See `tests/test_ai_error_paths.py` — `_FakeResp`, `_FakeChoice`, `_FakeRespMessage` pattern |
| OpenAI (rate limiter) | Mock `AsyncRateLimiter` or patch `AIService._rate_limiter` | See `tests/test_ai_sd_generate.py` patterns |
| Storage (for sidecar) | Mock `StorageProtocol` | See `tests/conftest.py` — `BaseDummyStorage` |

### Files to modify

| Area | File | Changes |
|------|------|---------|
| Models | `publisher_v2/src/publisher_v2/core/models.py` | Add `CaptionSpec.for_platforms()` static method; add `platform_captions` to `WorkflowResult` |
| AI service | `publisher_v2/src/publisher_v2/services/ai.py` | Add `generate_multi`, `generate_multi_with_sd` to `CaptionGeneratorOpenAI`; add `create_multi_caption_pair_from_analysis` to `AIService` |
| Workflow | `publisher_v2/src/publisher_v2/core/workflow.py` | Change caption generation to use `for_platforms` + `create_multi_caption_pair_from_analysis`; change publish loop to use `platform_captions[p.platform_name]` |
| Static config | `publisher_v2/src/publisher_v2/config/static/ai_prompts.yaml` | Add `platform_captions` section |
| Static loader | `publisher_v2/src/publisher_v2/config/static_loader.py` | Add `PlatformCaptionStyle` model and `platform_captions` field to `AIPromptsConfig` |
| Preview | `publisher_v2/src/publisher_v2/app.py` | Use `result.platform_captions` in preview loop instead of `format_caption(pub.platform_name, result.caption)` |
| Web service | `publisher_v2/src/publisher_v2/web/service.py` | Update `analyze_and_caption` to use `for_platforms` + multi-caption; extend `AnalysisResponse` |
| Web models | `publisher_v2/src/publisher_v2/web/models.py` | Add `platform_captions` to `AnalysisResponse` |
| Caption formatting | `publisher_v2/src/publisher_v2/utils/captions.py` | No logic changes; `format_caption` remains as safety net |

### Files to create

| Area | File |
|------|------|
| Tests | `publisher_v2/tests/test_ai_multi_caption.py` |
| Tests | `publisher_v2/tests/test_workflow_multi_caption.py` |
| Tests | `publisher_v2/tests/test_caption_spec.py` |
| Tests | `publisher_v2/tests/test_preview_multi_caption.py` (optional, can merge into existing) |
| Tests | `publisher_v2/tests/test_web_multi_caption.py` (optional, can merge into existing) |

### Key design decisions

1. **Single API call for all platforms**: The prompt enumerates all enabled platforms and their constraints. The LLM returns a JSON object with one key per platform. This is cost-neutral (same model, slightly more tokens) and avoids N round-trips.

2. **`CaptionSpec.for_platforms()` reads enabled publishers from config**: It checks `config.platforms.telegram_enabled`, `config.platforms.email_enabled`, `config.platforms.instagram_enabled` and builds specs only for enabled ones. Style/limits come from `get_static_config().ai_prompts.platform_captions`.

3. **Backwards compatibility via `for_config()`**: The existing method is preserved (delegates internally). `web/service.py` can use either path. Tests using `for_config` keep passing.

4. **`result.caption` remains for logging/sidecar**: The primary caption (first platform in the dict, or generic) is stored in `result.caption` for structured logging, sidecar metadata, and backward compat. `result.platform_captions` carries the full dict.

5. **SD caption is NOT per-platform**: There is still exactly one `sd_caption` per image. Only the social/posting captions are platform-adaptive. The SD prompt is for Stable Diffusion training data — platform is irrelevant.

6. **Caption override skips multi-generation**: When the web UI provides `caption_override`, it applies to all publishers as-is (just formatted per platform). This preserves the manual override workflow.

7. **`format_caption` remains as safety net**: Even though the LLM is instructed to respect platform limits, `format_caption` still runs on the output. This catches edge cases (LLM ignoring length, wrong hashtag count for Instagram, missing FetLife sanitization for email).

### Existing code to study before implementing

| What | Where | Why |
|------|-------|-----|
| Current `generate` method | `services/ai.py:267-295` | Understand prompt shape and length enforcement |
| Current `generate_with_sd` | `services/ai.py:302-338` | Understand JSON response parsing pattern for multi-output |
| `CaptionSpec.for_config` | `core/models.py:53-68` | The factory to extend |
| Workflow caption+publish flow | `core/workflow.py:314-401` | The integration point |
| Preview caption display | `app.py:137-167` | Preview output to update |
| Static config loader | `config/static_loader.py` | How YAML prompts are loaded |
| Prompt precedence (tenant vs static) | `services/ai.py:198-260` | Constructor precedence rules to respect |
| `AIService.create_caption_pair_from_analysis` | `services/ai.py:375-397` | Fallback pattern to replicate |

### Non-negotiables for this item

- [ ] **Preview mode**: Must display per-platform AI-generated captions (not formatted variants of one)
- [ ] **Secrets**: No changes to credential handling; OpenAI API key from config
- [ ] **Auth**: N/A (AI generation is not auth-gated directly)
- [ ] **Sidecar stability**: SD caption content/format unchanged; sidecar schema untouched
- [ ] **Coverage**: ≥80% on `ai.py`, `workflow.py`, `models.py` changes

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-025_platform-adaptive-captions.md
```
