# Implementation Handoff: PUB-040 — OpenAI Model Lifecycle Warnings

**Hardened:** 2026-03-16
**Status:** Ready for implementation

## For Claude Code

### Test-first targets

| AC | Test file | Key test cases |
|----|-----------|----------------|
| AC-01 | `publisher_v2/tests/test_model_lifecycle_warnings.py` | `ModelLifecycle(warning=..., severity="warning")` constructs |
| AC-02 | same | `ModelLifecycle(severity="unknown")` → `ValidationError` |
| AC-03 | same | `OpenAIConfig()` → both lifecycle fields `None` |
| AC-04 | same | `OpenAIConfig(vision_model_lifecycle=ModelLifecycle(...))` stores it |
| AC-05 | same | `OrchestratorAI.model_validate({...lifecycle dict...})` → dict stored |
| AC-06 | same | `OrchestratorAI.model_validate({...lifecycle: null...})` → `None` |
| AC-07 | same | Full v2 payload: valid vision lifecycle + null caption lifecycle → correct mapping |
| AC-08 | same | Malformed lifecycle dict (missing `severity`) → `None` on `OpenAIConfig`, no crash |
| AC-09 | same | V1 payload → both lifecycle fields `None` |
| AC-10 | same | `severity="warning"` → `logging.WARNING` with `model_role="vision"` |
| AC-11 | same | `severity="critical"` → `logging.ERROR` with `model_role="caption"` |
| AC-12 | same | `severity="info"` → `logging.INFO` |
| AC-13 | same | Both `None` → zero log records |
| AC-14 | same | Log output contains no `credentials_ref` or `api_key` |
| AC-15 | same | Fresh fetch → warning emitted; cache hit → no warning |
| AC-16 | same | Standalone mode → both `None`, no warnings |

### Mock boundaries

| External service | Mock strategy | Existing fixture |
|-----------------|---------------|------------------|
| Orchestrator runtime API | `unittest.mock.AsyncMock` on `OrchestratorClient.get_runtime_by_host` | Build fixture dicts matching `OrchestratorRuntimeResponse` shape |
| Orchestrator credentials API | `unittest.mock.AsyncMock` on `OrchestratorClient.resolve_credentials` | Existing pattern in `test_config_managed.py`, `config/test_orchestrator_usage.py` |
| Logging capture | `caplog` pytest fixture or `unittest.mock.patch` on `log_json` | Standard pytest `caplog` |
| Environment variables | `monkeypatch.setenv` / `monkeypatch.delenv` | Standard pytest pattern |

### Files likely touched

| Area | Files to modify | Files to create |
|------|-----------------|-----------------|
| Config models | `publisher_v2/src/publisher_v2/config/schema.py` | — |
| Orchestrator models | `publisher_v2/src/publisher_v2/config/orchestrator_models.py` | — |
| Orchestrator parsing | `publisher_v2/src/publisher_v2/config/source.py` | — |
| Tests | — | `publisher_v2/tests/test_model_lifecycle_warnings.py` |

### Implementation sequence

1. **`ModelLifecycle` model** (schema.py) — new Pydantic model with severity validator
2. **`OpenAIConfig` extension** (schema.py) — add two optional `ModelLifecycle | None` fields
3. **`OrchestratorAI` extension** (orchestrator_models.py) — add two `dict[str, Any] | None` fields
4. **`_build_app_config_v2` mapping** (source.py) — map lifecycle dicts → `ModelLifecycle` with try/except for malformed data
5. **Warning emitter** (source.py or new config/lifecycle.py) — `emit_model_lifecycle_warnings(openai_cfg)` function
6. **Call site** (source.py) — invoke emitter in `get_config()` after fresh fetch, before caching
7. **Tests** — all 16 ACs

### Key implementation details

#### `ModelLifecycle` (schema.py)

```python
class ModelLifecycle(BaseModel):
    warning: str
    shutdown_date: str
    recommended_replacement: str
    severity: str

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        allowed = {"info", "warning", "critical"}
        if v not in allowed:
            raise ValueError(f"severity must be one of {allowed}, got '{v}'")
        return v
```

#### `OpenAIConfig` extension (schema.py)

```python
vision_model_lifecycle: ModelLifecycle | None = Field(
    default=None, description="Advisory lifecycle metadata for vision model"
)
caption_model_lifecycle: ModelLifecycle | None = Field(
    default=None, description="Advisory lifecycle metadata for caption model"
)
```

#### `OrchestratorAI` extension (orchestrator_models.py)

```python
vision_model_lifecycle: dict[str, Any] | None = None
caption_model_lifecycle: dict[str, Any] | None = None
```

#### `_build_app_config_v2` mapping (source.py, in the AI block ~line 490)

```python
if cfg.ai.vision_model_lifecycle:
    try:
        openai_cfg.vision_model_lifecycle = ModelLifecycle.model_validate(cfg.ai.vision_model_lifecycle)
    except Exception:
        log_json(logger, logging.WARNING, "model_lifecycle_parse_error", model_role="vision")

if cfg.ai.caption_model_lifecycle:
    try:
        openai_cfg.caption_model_lifecycle = ModelLifecycle.model_validate(cfg.ai.caption_model_lifecycle)
    except Exception:
        log_json(logger, logging.WARNING, "model_lifecycle_parse_error", model_role="caption")
```

#### Warning emitter (source.py or config/lifecycle.py)

```python
_SEVERITY_TO_LEVEL = {
    "info": logging.INFO,
    "warning": logging.WARNING,
    "critical": logging.ERROR,
}

def emit_model_lifecycle_warnings(openai_cfg: OpenAIConfig) -> None:
    for role, lc in [("vision", openai_cfg.vision_model_lifecycle),
                     ("caption", openai_cfg.caption_model_lifecycle)]:
        if lc is None:
            continue
        level = _SEVERITY_TO_LEVEL.get(lc.severity, logging.WARNING)
        log_json(logger, level, "model_lifecycle_warning",
            model_role=role,
            warning=lc.warning,
            shutdown_date=lc.shutdown_date,
            recommended_replacement=lc.recommended_replacement,
            severity=lc.severity,
        )
```

#### Call site in `get_config()` (source.py ~line 200)

```python
# After _build_app_config_v2 returns and before caching:
emit_model_lifecycle_warnings(app_cfg.openai)

rc = RuntimeConfig(...)
self._runtime_cache.set(h, rc, ...)
return rc
```

### Non-negotiables for this item

- [ ] Preview mode: N/A (lifecycle warnings are observability-only, no side effects)
- [ ] Secrets: lifecycle log output must not contain `credentials_ref`, `api_key`, or any secret. Emitter only logs lifecycle-specific fields.
- [ ] Auth: N/A (no web endpoint changes)
- [ ] Coverage: ≥80% on affected modules (`config/schema.py`, `config/source.py`, `config/orchestrator_models.py`)
- [ ] Backward compatibility: all defaults preserve existing behavior. Missing lifecycle fields = `None` = no warnings.

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-040_model-lifecycle-warnings.md
```
