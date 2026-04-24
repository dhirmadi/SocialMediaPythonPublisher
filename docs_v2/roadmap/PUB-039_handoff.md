# Implementation Handoff: PUB-039 — AI Caption Feature Flags & Voice Profile

**Hardened:** 2026-03-16
**Status:** Ready for implementation

## For Claude Code

### Test-first targets

| AC | Test file | Key test cases |
|----|-----------|----------------|
| AC-01 | `publisher_v2/tests/test_caption_feature_flags.py` | `FeaturesConfig()` defaults: `alt_text_enabled=True`, `smart_hashtags_enabled=True`, `voice_matching_enabled=False` |
| AC-02 | same | `ContentConfig(voice_profile=None)` OK; `ContentConfig(voice_profile=["x"])` OK |
| AC-03 | same | `ContentConfig(voice_profile=[""])` → `ValidationError`; `ContentConfig(voice_profile=["a"]*21)` → `ValidationError` |
| AC-04 | same | `OrchestratorFeatures.model_validate({"publish_enabled": True, "alt_text_enabled": False})` → `alt_text_enabled=False` |
| AC-05 | same | `OrchestratorContent.model_validate({"voice_profile": ["x"]})` → `voice_profile=["x"]`; `OrchestratorContent.model_validate({})` → `voice_profile=None` |
| AC-06 | same | Full v2 payload with all new fields → `_build_app_config_v2` maps correctly |
| AC-07 | same | V2 payload missing new fields → defaults applied |
| AC-08 | same | V1 payload → defaults (no voice profile, flags at safe values) |
| AC-09 | same | `FEATURE_ALT_TEXT=false` in env → `alt_text_enabled=False`; absent → `True` |
| AC-10 | same | `CONTENT_SETTINGS='{"voice_profile":["a","b"]}'` → parsed into `ContentConfig` |
| AC-11 | same | `for_platforms()` with `voice_matching_enabled=True` + profile → examples start with profile entries |
| AC-12 | same | `for_platforms()` with `voice_matching_enabled=False` + profile → profile ignored |
| AC-13 | same | `for_platforms()` with `voice_matching_enabled=True` + `None`/empty profile → graceful no-op |
| AC-14 | same | `_safe_log_config({"voice_profile": [...]})` → redacted |
| AC-15 | same | No voice_profile content in structured log output |
| AC-16 | same | All defaults → caption pipeline output unchanged from baseline |

### Mock boundaries

| External service | Mock strategy | Existing fixture |
|-----------------|---------------|------------------|
| Orchestrator runtime API | `unittest.mock.AsyncMock` on `OrchestratorClient.get_runtime_by_host` | Build fixture dicts matching `OrchestratorRuntimeResponse` shape |
| Orchestrator credentials API | `unittest.mock.AsyncMock` on `OrchestratorClient.resolve_credentials` | Existing pattern in `test_config_managed.py` |
| OpenAI (for AC-16 baseline) | `unittest.mock.AsyncMock` on `AsyncOpenAI` | Existing pattern in AI tests |
| Static config YAML | `unittest.mock.patch` on `get_static_config` | Return `StaticConfig()` with known platform_captions |
| Environment variables | `monkeypatch.setenv` / `monkeypatch.delenv` | Standard pytest pattern |

### Files likely touched

| Area | Files to modify | Files to create |
|------|-----------------|-----------------|
| Config models | `publisher_v2/src/publisher_v2/config/schema.py` | — |
| Orchestrator models | `publisher_v2/src/publisher_v2/config/orchestrator_models.py` | — |
| Orchestrator parsing | `publisher_v2/src/publisher_v2/config/source.py` | — |
| Standalone loader | `publisher_v2/src/publisher_v2/config/loader.py` | — |
| Caption spec | `publisher_v2/src/publisher_v2/core/models.py` | — |
| Logging redaction | `publisher_v2/src/publisher_v2/config/loader.py` (REDACT_KEYS) | — |
| Tests | — | `publisher_v2/tests/test_caption_feature_flags.py` |

### Implementation sequence

1. **Models first**: Add fields to `FeaturesConfig`, `ContentConfig`, `OrchestratorFeatures`, `OrchestratorContent`
2. **Parsing**: Update `_build_app_config_v2` for `voice_profile` mapping, update `load_application_config` for new env vars
3. **Pipeline**: Modify `CaptionSpec.for_platforms()` to merge voice profile
4. **Logging**: Add `voice_profile` to `REDACT_KEYS`
5. **Tests**: Write tests covering all 16 ACs

### Key implementation details

#### `FeaturesConfig` (schema.py)
```python
alt_text_enabled: bool = Field(default=True, description="Enable AI alt-text generation (PUB-026)")
smart_hashtags_enabled: bool = Field(default=True, description="Enable smart hashtag generation (PUB-028)")
voice_matching_enabled: bool = Field(default=False, description="Enable voice profile injection for caption tone matching")
```

#### `ContentConfig` (schema.py)
```python
voice_profile: list[str] | None = Field(default=None, description="Operator example captions for few-shot tone")

@field_validator("voice_profile")
@classmethod
def validate_voice_profile(cls, v: list[str] | None) -> list[str] | None:
    if v is None:
        return v
    if len(v) > 20:
        raise ValueError("voice_profile may contain at most 20 examples")
    if any(not s.strip() for s in v):
        raise ValueError("voice_profile entries must be non-empty strings")
    return v
```

#### `CaptionSpec.for_platforms()` (models.py) — voice profile merge
```python
# After building spec from YAML registry:
voice_profile_examples: tuple[str, ...] = ()
if config.features.voice_matching_enabled and config.content.voice_profile:
    voice_profile_examples = tuple(config.content.voice_profile)

# For each spec:
specs[name] = CaptionSpec(
    ...,
    examples=voice_profile_examples + tuple(style_cfg.examples),  # VP first
    ...
)
```

#### `_build_app_config_v2` (source.py) — voice_profile mapping
```python
# In the content construction block:
ct = cfg.content
content = ContentConfig(
    hashtag_string=...,
    archive=...,
    debug=...,
    voice_profile=ct.voice_profile if ct else None,  # NEW
)
```

#### `load_application_config` (loader.py) — new env vars
```python
features_cfg = FeaturesConfig(
    ...,
    alt_text_enabled=parse_bool_env(os.environ.get("FEATURE_ALT_TEXT"), True, var_name="FEATURE_ALT_TEXT"),
    smart_hashtags_enabled=parse_bool_env(os.environ.get("FEATURE_SMART_HASHTAGS"), True, var_name="FEATURE_SMART_HASHTAGS"),
    voice_matching_enabled=parse_bool_env(os.environ.get("FEATURE_VOICE_MATCHING"), False, var_name="FEATURE_VOICE_MATCHING"),
)
```

### Non-negotiables for this item

- [ ] Preview mode: no behavioral change (flags are config-only for alt-text/hashtags; voice profile affects prompt content but not side effects)
- [ ] Secrets: `voice_profile` treated as sensitive user content — redacted in logs
- [ ] Auth: N/A (no web endpoint changes)
- [ ] Coverage: ≥80% on affected modules (`config/schema.py`, `config/source.py`, `config/loader.py`, `core/models.py`)
- [ ] Backward compatibility: all defaults preserve existing behavior

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-039_ai-caption-feature-flags.md
```
