# PUB-039 — AI Caption Feature Flags & Voice Profile

| Field | Value |
|-------|-------|
| **ID** | PUB-039 |
| **Category** | Config / AI |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Not Started |
| **Dependencies** | PUB-025 (Done), PUB-035 (Done) |
| **GitHub Issue** | [dhirmadi/SocialMediaPythonPublisher#63](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/63) |
| **Orchestrator PR** | [dhirmadi/platform-orchestrator#168](https://github.com/dhirmadi/platform-orchestrator/pull/168) |

---

## Problem

The platform orchestrator shipped **AI_01** — runtime projection + tenant UI for AI caption controls. The orchestrator now projects three new feature flags and an optional `voice_profile` array in the runtime config payload. Publisher V2 does not yet parse or honor these fields, meaning:

- Operators cannot toggle alt-text, smart hashtags, or voice matching per instance
- The `voice_profile` (few-shot example captions) from the orchestrator is ignored
- Existing publisher features (PUB-026 alt text, PUB-028 hashtags, PUB-029 voice matching) have no runtime gating mechanism

## Solution

Extend config models and orchestrator parsing to consume the new fields. Wire voice profile into the existing caption generation pipeline (PUB-035's few-shot mechanism). Alt-text and hashtag flags are config-only for now — behavioral gating will be added when PUB-026/PUB-028 are implemented.

---

## Parts

### Part A — Config Model Extension

**`FeaturesConfig`** (`config/schema.py`) — add three boolean fields with safe defaults matching the orchestrator contract:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `alt_text_enabled` | `bool` | `True` | Future gate for PUB-026 alt-text generation |
| `smart_hashtags_enabled` | `bool` | `True` | Future gate for PUB-028 smart hashtag generation |
| `voice_matching_enabled` | `bool` | `False` | Gates voice profile injection into caption prompts |

**`ContentConfig`** (`config/schema.py`) — add one optional field:

| Field | Type | Default | Constraint | Purpose |
|-------|------|---------|------------|---------|
| `voice_profile` | `list[str] \| None` | `None` | When present: 1–20 non-empty strings | Operator-managed example captions for few-shot tone |

Pydantic validator on `voice_profile`: if the list is present, reject empty strings and lists with >20 items (matches orchestrator's 422 validation).

### Part B — Orchestrator Model Extension

**`OrchestratorFeatures`** (`config/orchestrator_models.py`) — add the three boolean fields with matching defaults. These are already safe due to `extra="allow"`, but explicit fields ensure they flow through `model_dump()` → `FeaturesConfig(**...)` in `_build_app_config_v1` and `_build_app_config_v2`.

| Field | Type | Default |
|-------|------|---------|
| `alt_text_enabled` | `bool` | `True` |
| `smart_hashtags_enabled` | `bool` | `True` |
| `voice_matching_enabled` | `bool` | `False` |

**`OrchestratorContent`** (`config/orchestrator_models.py`) — add:

| Field | Type | Default |
|-------|------|---------|
| `voice_profile` | `list[str] \| None` | `None` |

### Part C — Runtime Parsing in `_build_app_config_v2`

In `source.py::_build_app_config_v2`:

1. The `FeaturesConfig(**cfg.features.model_dump())` pattern already passes through all known fields — once Part B adds the fields to `OrchestratorFeatures`, they flow automatically.
2. For `voice_profile`: when building `ContentConfig`, read `cfg.content.voice_profile` (if `cfg.content` is not None) and pass it to the `ContentConfig` constructor.
3. In `_build_app_config_v1`: new feature flags should use their safe defaults (no orchestrator v1 payload includes these fields). `voice_profile` is `None`.

### Part D — Standalone Mode (`loader.py`)

In `load_application_config`:
- `FeaturesConfig` construction already reads `FEATURE_*` env vars. Add three new env var mappings:
  - `FEATURE_ALT_TEXT` → `alt_text_enabled` (default `True`)
  - `FEATURE_SMART_HASHTAGS` → `smart_hashtags_enabled` (default `True`)
  - `FEATURE_VOICE_MATCHING` → `voice_matching_enabled` (default `False`)
- `ContentConfig` construction: read `voice_profile` from `CONTENT_SETTINGS` JSON env var if present (optional array field). In standalone mode this is typically `None`.

### Part E — Voice Profile → Caption Pipeline

When `voice_matching_enabled` is `True` and `voice_profile` is non-empty:

1. In `CaptionSpec.for_platforms()` (`core/models.py`): after building each `CaptionSpec` from the static YAML registry, **prepend** the `voice_profile` entries to the spec's `examples` tuple. Orchestrator voice profile takes precedence (listed first) over YAML examples.
2. This means the existing `build_platform_block()` in `ai.py` automatically includes them in the prompt — no changes needed in the AI service layer.
3. When `voice_matching_enabled` is `False`: do not inject `voice_profile` into `CaptionSpec.examples`, even if `voice_profile` is present in config. The YAML-only examples still apply.

The `voice_profile` list is passed via `ApplicationConfig.content.voice_profile`. `CaptionSpec.for_platforms()` already receives `config: ApplicationConfig`, so it can read `config.features.voice_matching_enabled` and `config.content.voice_profile`.

### Part F — Logging Safety

`voice_profile` contains sensitive user content (their personal captions). The existing `SanitizingFilter` uses regex patterns and cannot pattern-match arbitrary text.

Instead:
1. Add `"voice_profile"` to the `REDACT_KEYS` set in `config/loader.py` (used by `_safe_log_config`).
2. In any structured log that might include config data, ensure `voice_profile` is omitted or replaced with a count (e.g., `"voice_profile": "<3 examples>"`).
3. Do **not** attempt to regex-match voice profile content in `SanitizingFilter` — that approach is impractical for free-form text.

### Part G — Tests

All tests in `publisher_v2/tests/test_caption_feature_flags.py` (new file):

1. **Config model tests** — `FeaturesConfig` defaults, `ContentConfig` with/without `voice_profile`, validation rejects empty strings and >20 items.
2. **Orchestrator parsing tests** — `_build_app_config_v2` with new fields present, absent, and partially present.
3. **Standalone parsing tests** — `load_application_config` with new `FEATURE_*` env vars.
4. **Voice profile → CaptionSpec tests** — `for_platforms()` with `voice_matching_enabled=True` + profile prepends examples; with `False` ignores profile.
5. **Logging redaction tests** — `_safe_log_config` redacts `voice_profile`.

---

## Acceptance Criteria

### Config Models (Part A)

1. **AC-01**: `FeaturesConfig` has `alt_text_enabled: bool = True`, `smart_hashtags_enabled: bool = True`, `voice_matching_enabled: bool = False`. Constructing `FeaturesConfig()` with no arguments produces these defaults.
2. **AC-02**: `ContentConfig` has `voice_profile: list[str] | None = None`. Constructing with `voice_profile=None` and `voice_profile=["example"]` both succeed.
3. **AC-03**: `ContentConfig(voice_profile=[""])` raises `ValidationError` (empty strings rejected). `ContentConfig(voice_profile=["a"] * 21)` raises `ValidationError` (>20 items rejected).

### Orchestrator Parsing (Parts B, C)

4. **AC-04**: `OrchestratorFeatures` model accepts `alt_text_enabled`, `smart_hashtags_enabled`, `voice_matching_enabled` from a runtime payload dict. Missing fields default safely.
5. **AC-05**: `OrchestratorContent` model accepts `voice_profile` as `list[str] | None`. Missing field defaults to `None`.
6. **AC-06**: Given a schema v2 runtime payload with `features.voice_matching_enabled=true` and `content.voice_profile=["tone example"]`, `_build_app_config_v2` produces an `ApplicationConfig` where `config.features.voice_matching_enabled is True` and `config.content.voice_profile == ["tone example"]`.
7. **AC-07**: Given a schema v2 runtime payload where `features` lacks the three new keys and `content` lacks `voice_profile`, `_build_app_config_v2` produces an `ApplicationConfig` with default values (`alt_text_enabled=True`, `smart_hashtags_enabled=True`, `voice_matching_enabled=False`, `voice_profile=None`).
8. **AC-08**: In schema v1 parsing (`_build_app_config_v1`), the three new feature flags use their safe defaults and `voice_profile` is `None`.

### Standalone Mode (Part D)

9. **AC-09**: `load_application_config` reads `FEATURE_ALT_TEXT`, `FEATURE_SMART_HASHTAGS`, `FEATURE_VOICE_MATCHING` from env vars with correct defaults when absent.
10. **AC-10**: `CONTENT_SETTINGS` JSON env var can include `"voice_profile": ["a", "b"]` and the parsed `ContentConfig` reflects it.

### Voice Profile Pipeline (Part E)

11. **AC-11**: When `voice_matching_enabled=True` and `voice_profile=["vp1", "vp2"]`, `CaptionSpec.for_platforms()` returns specs where each spec's `examples` tuple starts with `("vp1", "vp2", ...)` followed by any YAML-defined examples.
12. **AC-12**: When `voice_matching_enabled=False` and `voice_profile=["vp1"]`, `CaptionSpec.for_platforms()` returns specs whose `examples` contain only the YAML-defined examples (voice profile ignored).
13. **AC-13**: When `voice_matching_enabled=True` and `voice_profile=None` (or empty list), `CaptionSpec.for_platforms()` returns specs with only YAML-defined examples (no crash, graceful no-op).

### Logging Safety (Part F)

14. **AC-14**: `_safe_log_config({"voice_profile": ["my caption"]})` returns `{"voice_profile": "***REDACTED***"}`.
15. **AC-15**: No `voice_profile` string content appears in any structured log output during config loading or caption generation.

### Backward Compatibility

16. **AC-16**: Existing caption pipeline (PUB-025 multi-caption, PUB-035 history) produces identical output when all new fields are at defaults (`alt_text_enabled=True`, `smart_hashtags_enabled=True`, `voice_matching_enabled=False`, `voice_profile=None`).

---

## Out of Scope

- **Behavioral gating for alt-text and hashtags**: PUB-026 and PUB-028 will implement the actual generation code and use the flags added here. This item only adds the config fields.
- **Orchestrator API changes**: This is publisher-only consumption.
- **Admin UI exposure**: No web UI changes for these flags.

## Coordination Notes

This item provides the **runtime gating layer** that PUB-026 (alt text), PUB-028 (smart hashtags), and PUB-029 (brand voice) will use. Those items implement the actual AI features; this item ensures the feature flags and voice profile are consumed from the orchestrator and wired into the pipeline.

PUB-035 (Caption Context Intelligence) already has a `PlatformCaptionStyle.examples` mechanism for few-shot prompting from `ai_prompts.yaml`. The `voice_profile` from the orchestrator is operator-managed and **prepends** to the YAML examples (orchestrator voice takes precedence, listed first in the prompt).

---

2026-03-16 — Spec hardened for Claude Code handoff
