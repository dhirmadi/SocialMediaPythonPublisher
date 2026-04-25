# PUB-026 — AI Alt Text Generation: Implementation Summary

**Status:** Implementation Complete
**Date:** 2026-04-25

## Files Changed

### Source

- `publisher_v2/src/publisher_v2/core/models.py` — Added `alt_text: str | None = None` to `ImageAnalysis`.
- `publisher_v2/src/publisher_v2/services/ai.py` — Extended `_DEFAULT_VISION_SYSTEM_PROMPT` and `_DEFAULT_VISION_USER_PROMPT` to request an `alt_text` key (≤125 chars, screen-reader-oriented). Parser populates `alt_text` via `_opt_str(data.get("alt_text"))`. JSON-decode-error fallback dict carries `"alt_text": None`.
- `publisher_v2/src/publisher_v2/config/static/ai_prompts.yaml` — Mirrored `alt_text` extension in the YAML-overridable prompt.
- `publisher_v2/src/publisher_v2/core/workflow.py` — New `_build_publisher_context(analysis: ImageAnalysis | None)` helper builds the publisher context dict, adding `alt_text` only when `features.alt_text_enabled` is True and the analysis has one. Replaces the inline `context={"analysis_tags": …}` construction.
- `publisher_v2/src/publisher_v2/utils/captions.py` — `build_metadata_phase2` includes `alt_text` when present.
- `publisher_v2/src/publisher_v2/utils/preview.py` — `print_vision_analysis` displays an "Alt text:" line when present.
- `publisher_v2/src/publisher_v2/web/models.py` — `AnalysisResponse` adds `alt_text: str | None = None`.
- `publisher_v2/src/publisher_v2/web/service.py` — `analyze_and_caption` populates `alt_text` from the analysis when `features.alt_text_enabled` is True.

### Tests

- `publisher_v2/tests/test_alt_text.py` — New file: 15 tests covering AC-01..AC-12 (model field, prompt extensions, parser, JSON fallback, missing key, sidecar phase2 inclusion/omission, web response model + endpoint, preview output, and four scenarios for `_build_publisher_context` covering AC-06/AC-07).
- `publisher_v2/tests/test_publishers_platforms.py` — Added `"alt_text": …` to the Email and Telegram test contexts (AC-08: publishers ignore unknown context keys; assertions unchanged).

### Docs

- `docs_v2/roadmap/PUB-026_ai-alt-text.md` — Hardened spec.
- `docs_v2/roadmap/PUB-026_handoff.md` — Implementation handoff.
- `docs_v2/roadmap/PUB-026_summary.md` — This file.

## Acceptance Criteria

- [x] AC-01 — `ImageAnalysis.alt_text: str | None` defaulting to `None` (`test_imageanalysis_accepts_alt_text_*`)
- [x] AC-02 — Both default vision prompts include `alt_text` + ≤125 char + screen-reader guidance (`test_default_vision_prompts_include_alt_text`)
- [x] AC-03 — `analyze()` parses `alt_text` (`test_vision_analyzer_parses_alt_text`)
- [x] AC-04 — JSON decode error fallback carries `alt_text=None` (`test_vision_analyzer_json_decode_error_sets_alt_text_none`)
- [x] AC-05 — Missing `alt_text` key → `None` (`test_vision_analyzer_missing_alt_text_is_none`)
- [x] AC-06 — Context dict includes `alt_text` when flag on + non-None (`test_ac06_context_includes_alt_text_when_enabled_and_present`)
- [x] AC-07 — Context omits `alt_text` when flag off (`test_ac07_context_omits_alt_text_when_disabled`)
- [x] AC-08 — Telegram + Email accept `alt_text` in context without error (`test_email_publisher_sends_and_confirms`, `test_telegram_publisher_success`)
- [x] AC-09 — Phase 2 sidecar includes `alt_text` when present (`test_build_metadata_phase2_includes_alt_text_when_present`)
- [x] AC-10 — Phase 2 omits `alt_text` when None (`test_build_metadata_phase2_omits_alt_text_when_none`)
- [x] AC-11 — `AnalysisResponse.alt_text` + endpoint returns it when enabled (`test_analysis_response_model_has_alt_text_field`, `test_web_analyze_and_caption_returns_alt_text_when_enabled`)
- [x] AC-12 — CLI preview prints "Alt text:" line when present (`test_preview_print_vision_analysis_includes_alt_text`)
- [x] AC-13 — No regressions: full suite 932 passed.

## Test Results

- 15 new tests in `test_alt_text.py`, all pass.
- 2 existing publisher tests extended (additive only, no changed assertions).
- Full suite: **932 passed, 0 failed**.

## Quality Gates

- Format: ✅ `ruff format --check` — 163 files clean
- Lint: ✅ `ruff check` — All checks passed
- Type check: ✅ `mypy --ignore-missing-imports` — 50 source files clean
- Tests: 932 passed, 0 failed
- Coverage on affected modules:
  - `core/models.py`: 97%
  - `core/workflow.py`: 92%
  - `services/ai.py`: 92%
  - `utils/captions.py`: 95%
  - `utils/preview.py`: 95%
  - `web/models.py`: 100%
- Overall coverage: **88%** (≥85% gate).

## Notes

- **Always-on prompt, gated consumption:** Per the hardened spec, `alt_text` is always requested from OpenAI (negligible token cost) but only consumed downstream when `features.alt_text_enabled=True`. The feature flag gates the publisher context, the web response, and (transitively) any sidecar inclusion controlled by callers. This avoids conditional prompt mutation.
- **No Instagram integration in this item:** The original spec mentioned Instagram's `accessibility_caption`, but the hardened spec removed it because Instagram is being deprecated (GH #67). Future Bluesky (PUB-027) and Mastodon (PUB-030) publishers will consume `context["alt_text"]` when implemented.
- **Backward compatibility:** All existing `ImageAnalysis(...)` constructions without `alt_text` work unchanged (default `None`). Existing publisher tests pass with the new key in their contexts.
- **Type tightening:** `_build_publisher_context` is typed `ImageAnalysis | None` (not `object | None`), and uses direct attribute access instead of `getattr` since the type is known.
- **Preview safety:** N/A — alt text is a display-only addition to the existing preview output. No new side effects.
