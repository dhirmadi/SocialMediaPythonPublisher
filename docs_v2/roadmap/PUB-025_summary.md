# PUB-025 — Platform-Adaptive Captions: Implementation Summary

**Status:** Implementation Complete
**Date:** 2026-04-13

## Files Changed

- `publisher_v2/src/publisher_v2/config/static/ai_prompts.yaml` — Added `platform_captions` section with telegram, instagram, email, and generic style definitions
- `publisher_v2/src/publisher_v2/config/static_loader.py` — Added `PlatformCaptionStyle` model and `platform_captions` field to `AIPromptsConfig`
- `publisher_v2/src/publisher_v2/core/models.py` — Added `CaptionSpec.for_platforms()` static method; deprecated `for_config()` (delegates to `for_platforms()`); added `platform_captions` field to `WorkflowResult`
- `publisher_v2/src/publisher_v2/services/ai.py` — Added `generate_multi()` and `generate_multi_with_sd()` to `CaptionGeneratorOpenAI`; added `create_multi_caption_pair_from_analysis()` to `AIService` with fallback for generators lacking multi-caption support
- `publisher_v2/src/publisher_v2/core/workflow.py` — Changed caption generation to use `for_platforms()` + `create_multi_caption_pair_from_analysis()`; publish loop now uses `platform_captions.get(p.platform_name, caption)` with `format_caption()` safety net
- `publisher_v2/src/publisher_v2/app.py` — Preview mode now uses `result.platform_captions` for per-platform display
- `publisher_v2/src/publisher_v2/web/models.py` — Added `platform_captions: dict[str, str] | None` to `AnalysisResponse`
- `publisher_v2/src/publisher_v2/web/service.py` — Updated `analyze_and_caption` to use `for_platforms()` + `create_multi_caption_pair_from_analysis()`
- `publisher_v2/tests/conftest.py` — Added `create_multi_caption_pair_from_analysis` to `BaseDummyAI`
- `publisher_v2/tests/test_app_cli.py` — Added `platform_captions={}` to `mock_workflow_result` fixture
- `publisher_v2/tests/web/test_web_service_coverage.py` — Added mock for `create_multi_caption_pair_from_analysis`

## Files Created

- `publisher_v2/tests/test_caption_spec.py` — 9 tests for `CaptionSpec.for_platforms()` and `for_config()` backward compat
- `publisher_v2/tests/test_ai_multi_caption.py` — 13 tests for `generate_multi`, `generate_multi_with_sd`, SD fallback, prompt content
- `publisher_v2/tests/test_workflow_multi_caption.py` — 5 tests for workflow integration, caption override, format_caption safety net
- `publisher_v2/tests/test_preview_multi_caption.py` — 2 tests for WorkflowResult.platform_captions
- `publisher_v2/tests/test_web_multi_caption.py` — 2 tests for AnalysisResponse.platform_captions

## Acceptance Criteria

- [x] AC1 — Multi-platform `generate_multi` sends single API call, returns dict per platform (test: `test_generate_multi_returns_dict_per_platform`, `test_single_openai_call`)
- [x] AC2 — Captions exceeding max_length truncated with ellipsis (test: `test_caption_truncated_when_exceeds_max_length`)
- [x] AC3 — Missing platform key raises AIServiceError (test: `test_missing_platform_key_raises_error`)
- [x] AC4 — Uses `response_format=json_object` (test: `test_uses_json_response_format`)
- [x] AC5 — Telegram style in prompt (test: `test_telegram_style_in_prompt`)
- [x] AC6 — Instagram style in prompt (test: `test_instagram_style_in_prompt`)
- [x] AC7 — Email style in prompt (test: `test_email_style_in_prompt`)
- [x] AC8 — Styles from ai_prompts.yaml, not hardcoded (test: `test_platform_styles_loaded_from_yaml`)
- [x] AC9 — Each publisher receives platform-specific caption (test: `test_each_publisher_receives_own_caption`)
- [x] AC10 — format_caption still applies as safety net (test: `test_format_caption_still_applied_as_safety_net`)
- [x] AC11 — Caption override applies to all publishers (test: `test_caption_override_applies_to_all_publishers`)
- [x] AC12 — Single publisher equivalent to current behavior (test: `test_single_publisher_generates_single_caption`)
- [x] AC13 — `generate_multi_with_sd` produces captions + sd_caption (test: `test_generate_multi_with_sd_returns_captions_plus_sd`)
- [x] AC14 — SD caption format unchanged (test: `test_sd_caption_format_unchanged`)
- [x] AC15 — SD fallback to generate_multi (test: `test_sd_fallback_to_generate_multi`)
- [x] AC16 — `for_platforms()` returns enabled only (test: `test_for_platforms_returns_enabled_only`, `test_for_platforms_filters_disabled`)
- [x] AC17 — `for_config()` still works deprecated (test: `test_for_config_still_works_deprecated`)
- [x] AC18 — Preview shows per-platform captions (test: `test_workflow_result_has_platform_captions`)
- [x] AC19 — AnalysisResponse gains platform_captions (test: `test_analysis_response_includes_platform_captions`)
- [x] AC20 — Zero new ruff/mypy violations
- [x] AC21 — Full test coverage per handoff spec

## Test Results

- 640 passed, 1 failed (pre-existing: `test_email_publisher_sends_and_confirms`)
- 31 new tests added, all passing

## Quality Gates

- Format: zero reformats needed
- Lint: zero violations
- Type check: zero errors
- Tests: 640 passed, 1 pre-existing failure
- Coverage: 88% overall (>85% gate); affected modules: models.py 97%, ai.py 89%, workflow.py 93%, static_loader.py 97%, app.py 97%, web/models.py 100%

## Notes

- `AIService.create_multi_caption_pair_from_analysis` includes a backward-compatible fallback: if the generator doesn't have `generate_multi` (custom test generators, future plugins), it falls back to the single-caption path. This avoids breaking existing tests while enabling the multi-caption path for production `CaptionGeneratorOpenAI`.
- `CaptionSpec.for_config()` is preserved as a thin wrapper that delegates to `for_platforms()` and returns the first spec. All existing callers continue to work unchanged.
- The workflow uses `hasattr` to detect multi-caption support on the AI service, ensuring backward compatibility with `BaseDummyAI` and other test doubles that don't implement the new method.
