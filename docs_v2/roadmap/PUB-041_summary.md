# PUB-041 — Vision Cost Optimization & Richer Caption Inputs: Implementation Summary

**Status:** Implementation Complete
**Date:** 2026-04-25

## Files Changed

### Source

- `publisher_v2/src/publisher_v2/config/schema.py` — Added 5 vision fields (`vision_max_dimension`, `vision_detail`, `vision_fallback_enabled`, `vision_fallback_max_dimension`, `vision_fallback_detail`) with `field_validator` rejecting detail values outside `{low, high, auto}`.
- `publisher_v2/src/publisher_v2/config/orchestrator_models.py` — Added matching optional fields on `OrchestratorAI` for runtime payload mapping.
- `publisher_v2/src/publisher_v2/config/source.py` — Extracted `apply_orchestrator_ai_to_openai_cfg(ai, openai_cfg)` helper that mirrors the previous inline mapping, now including the 5 PUB-041 vision fields. `_build_app_config_v2` delegates to this helper, which is also unit-tested directly.
- `publisher_v2/src/publisher_v2/config/loader.py` — `_load_openai_settings_from_env` parses the 5 vision fields from `OPENAI_SETTINGS` JSON; loader passes them into `OpenAIConfig` constructor.
- `publisher_v2/src/publisher_v2/utils/images.py` — New `resize_image_bytes(data, max_dimension, quality=85)` helper using LANCZOS and JPEG re-encode (RGBA/P/LA→RGB).
- `publisher_v2/src/publisher_v2/services/ai.py` —
  - `VisionAnalyzerOpenAI.__init__` reads new vision config fields.
  - Refactored `analyze()` into a public method that prepares the image once via `_prepare_image_url` (download + resize, or legacy passthrough), then calls `_analyze_core(image_url, max_dim, detail, resized)` (decorated with `@retry(stop=stop_after_attempt(3))`); on `AIServiceError`, fires single fallback attempt at higher quality if enabled.
  - `_prepare_image_url` lives outside the retry boundary, so transient OpenAI errors do NOT cause repeat downloads (one download per chain — primary, fallback).
  - Download uses `httpx` + `resize_image_bytes` (run in `asyncio.to_thread`); emits a base64 JPEG data URL with `detail` parameter; legacy passthrough when `max_dimension == 0`.
  - Added `vision_fallback_triggered` (WARNING) and `vision_fallback_result` (INFO) structured log events; `vision_analysis` log enriched with `detail`, `max_dimension`, `resized` fields.
  - Added `_combine_usages` helper to accumulate primary + fallback `AIUsage`.
  - Added `build_analysis_context(analysis)` helper. Replaced inline `description=…, mood=…, tags=…` construction at three call sites (`generate`, `generate_with_sd`, `_build_multi_prompt`).

### Tests

- `publisher_v2/tests/test_vision_cost_optimization.py` — New file covering AC-01..AC-11, AC-17..AC-21 (resize utility, config defaults, validators, env parsing, orchestrator mapping, analyzer resize/data-URL flow, detail param, legacy bypass, quality-escalation fallback paths).
- `publisher_v2/tests/test_analysis_context.py` — New file covering AC-12..AC-16 (helper produces bounded context, omits None fields, truncates strings/lists, excludes sensitive fields, all three call sites use the helper).
- `publisher_v2/tests/test_ai_error_paths.py`, `publisher_v2/tests/test_ai_usage.py`, `publisher_v2/tests/test_ai_vision_analysis_telemetry.py`, `publisher_v2/tests/test_vision_analyzer_expanded_fields.py` — Pre-existing analyzer tests updated to opt into legacy passthrough config (`vision_max_dimension=0`, `vision_fallback_enabled=False`) per AC-21.

### Docs

- `docs_v2/roadmap/PUB-041_plan.yaml` — Implementation plan (this commit).
- `docs_v2/roadmap/PUB-041_summary.md` — This file.

## Acceptance Criteria

- [x] AC-01 — 4000×6000 → 683×1024 data URL (`test_ac01_resizes_4000x6000_and_sends_data_url`)
- [x] AC-02 — `detail` field matches config (`test_ac02_detail_field_matches_config`)
- [x] AC-03 — `max_dimension=0` passes URL directly, no download (`test_ac03_zero_max_dimension_passes_url_directly`)
- [x] AC-04 — Small image not upscaled, still data URL (`test_ac04_small_image_no_upscale_still_data_url`)
- [x] AC-05 — Aspect ratio preserved (`test_ac05_aspect_ratio_preserved`)
- [x] AC-06 — `resize_image_bytes` helper (`TestResizeImageBytes`)
- [x] AC-07 — Fallback fires with higher settings on `AIServiceError` (`test_ac07_fallback_called_with_higher_settings_on_aiservice_error`)
- [x] AC-08 — `vision_fallback_triggered` WARNING log (`test_ac08_fallback_warning_log_emitted`)
- [x] AC-09 — Disabled or failing fallback re-raises `AIServiceError` (`test_ac09_fallback_disabled_raises_aiservice_error`, `test_ac09_fallback_also_fails_raises_aiservice_error`)
- [x] AC-10 — Fallback adds at most one chain (`test_ac10_fallback_adds_at_most_one_additional_call_chain`)
- [x] AC-11 — Combined `AIUsage` returned (`test_ac11_returns_combined_usage`)
- [x] AC-12 — Optional fields included when non-None (`test_ac12_includes_optional_fields_when_present`)
- [x] AC-13 — None fields omitted (`test_ac13_none_fields_omitted`)
- [x] AC-14 — String 50-char and list 10-item caps (`test_ac14_long_strings_truncated_at_50_chars`, `test_ac14_aesthetic_terms_capped_at_10`)
- [x] AC-15 — Sensitive fields excluded (`test_ac15_excluded_fields_never_included`)
- [x] AC-16 — All three call sites use helper (`test_ac16_call_sites_use_helper`)
- [x] AC-17 — Defaults: 1024 / "low" / True / 2048 / "high" (`test_ac17_defaults`)
- [x] AC-18 — Validator rejects bad detail (`test_ac18_validator_rejects_invalid_detail`, `test_ac18_validator_accepts_low_high_auto`)
- [x] AC-19 — Orchestrator v2 maps vision fields (`test_ac19_orchestrator_v2_maps_vision_fields`, `test_ac19_build_app_config_v2_maps_vision_fields`)
- [x] AC-20 — `OPENAI_SETTINGS` parses vision fields (`test_ac20_openai_settings_parses_vision_fields`, `test_ac20_openai_settings_defaults_when_missing`)
- [x] AC-21 — Legacy passthrough when `max_dimension=0` + `detail="high"` (`test_ac21_legacy_behavior_no_resize_high_detail`)

## Test Results

- New tests for PUB-041: 30 passed (test_vision_cost_optimization.py = 18; test_analysis_context.py = 12).
- Full suite: **898 passed, 0 failed** in ~52s.

## Quality Gates

- Format: PASSED (`uv run ruff format --check publisher_v2/`)
- Lint: PASSED (`uv run ruff check publisher_v2/`)
- Type check: PASSED (mypy on changed files: schema, orchestrator_models, source, loader, services/ai, utils/images)
- Tests: 898 passed, 0 failed
- Coverage on affected modules:
  - `services/ai.py`: 92%
  - `utils/images.py`: 96%
  - `config/schema.py`: 98%
  - `config/orchestrator_models.py`: 100%
  - `config/loader.py`: 96%
  - `config/source.py`: 84%
- Overall coverage: **88%** (gate ≥85%).

## Notes

- **Retry semantics:** `_analyze_core` retains the existing `@retry(stop_after_attempt(3))` from tenacity; the fallback path is a *quality escalation* triggered only after all 3 retries on the cheap path raise `AIServiceError`. Fallback path also has its own 3 retries — at most 6 OpenAI calls in total when both paths exhaust.
- **Download placement:** Image preparation (download + resize) lives in `_prepare_image_url`, called once per chain *outside* the `_analyze_core` retry boundary. OpenAI-side retries reuse the prepared data URL — at most 1 download per chain (primary, fallback) regardless of OpenAI retry count.
- **Pre-existing test compatibility:** Pre-PUB-041 analyzer tests were updated minimally to opt into AC-21 legacy mode (`vision_max_dimension=0, vision_fallback_enabled=False`). No pre-existing assertions were changed — only the config setup was extended.
- **Async hygiene:** `httpx.AsyncClient` is async-native; `resize_image_bytes` is wrapped in `asyncio.to_thread()` to keep Pillow off the event loop.
- **Preview safety:** No publish/archive/state mutation occurs in the analyzer path; resize + low detail is purely a cost-shape change. Preview mode is unaffected.
- **API keys in tests:** All test API keys use stub patterns (`sk-test`, `sk-test-key-for-testing`, `sk-xxxxx…`) consistent with the existing fixtures and short enough not to match real OpenAI key formats.
