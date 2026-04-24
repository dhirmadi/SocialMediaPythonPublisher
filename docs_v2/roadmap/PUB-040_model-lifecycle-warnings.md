# PUB-040 — OpenAI Model Lifecycle Warnings

| Field | Value |
|-------|-------|
| **ID** | PUB-040 |
| **Category** | Config / Observability |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Not Started |
| **Dependencies** | PUB-022 (Done) |
| **GitHub Issue** | [dhirmadi/SocialMediaPythonPublisher#64](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/64) |
| **Orchestrator PR** | [dhirmadi/platform-orchestrator#169](https://github.com/dhirmadi/platform-orchestrator/pull/169) |

---

## Problem

The platform orchestrator shipped **AI_02** — non-secret OpenAI model lifecycle metadata projected onto the runtime `ai` block. When an operator's configured model is approaching deprecation or shutdown, the orchestrator annotates the runtime payload with advisory lifecycle objects. Publisher V2 currently ignores these fields, so operators get no warning until OpenAI rejects API calls with a deprecated model — causing silent failures in production.

## Solution

Parse the lifecycle metadata from the runtime payload, store it on `OpenAIConfig`, and emit structured log warnings on every fresh config fetch so operators can update model configuration proactively.

---

## Parts

### Part A — `ModelLifecycle` Pydantic Model

New model in `config/schema.py`:

| Field | Type | Constraint |
|-------|------|------------|
| `warning` | `str` | Required. e.g. `deprecated_model` |
| `shutdown_date` | `str` | Required. ISO `YYYY-MM-DD` string (no date validation — orchestrator is authoritative) |
| `recommended_replacement` | `str` | Required. Operator-facing model suggestion |
| `severity` | `str` | Required. One of `info`, `warning`, `critical` |

Pydantic `field_validator` on `severity`: must be one of `{"info", "warning", "critical"}`. If the orchestrator sends an unknown severity, the `OrchestratorAI` model has `extra="allow"` so it won't crash at the wire level — but `ModelLifecycle` validation will reject it. The parsing layer (Part C) catches `ValidationError` and logs a warning instead of crashing.

### Part B — `OpenAIConfig` Extension

Add two optional fields to `OpenAIConfig` (`config/schema.py`):

| Field | Type | Default |
|-------|------|---------|
| `vision_model_lifecycle` | `ModelLifecycle \| None` | `None` |
| `caption_model_lifecycle` | `ModelLifecycle \| None` | `None` |

These are advisory-only. They are not consumed by AI service calls — only by the warning emitter (Part D).

### Part C — Orchestrator Model & Parsing

**`OrchestratorAI`** (`config/orchestrator_models.py`) — add two optional fields:

| Field | Type | Default |
|-------|------|---------|
| `vision_model_lifecycle` | `dict[str, Any] \| None` | `None` |
| `caption_model_lifecycle` | `dict[str, Any] \| None` | `None` |

Use `dict[str, Any] | None` (not `ModelLifecycle`) at the orchestrator wire level so malformed payloads don't crash `OrchestratorConfigV2.model_validate()`. The conversion to `ModelLifecycle` happens in the mapping layer.

**`_build_app_config_v2`** (`config/source.py`) — in the AI settings block (after line ~490), map the lifecycle fields:

```python
if cfg.ai.vision_model_lifecycle:
    try:
        openai_cfg.vision_model_lifecycle = ModelLifecycle.model_validate(cfg.ai.vision_model_lifecycle)
    except ValidationError:
        pass  # malformed lifecycle data — log and continue
if cfg.ai.caption_model_lifecycle:
    try:
        openai_cfg.caption_model_lifecycle = ModelLifecycle.model_validate(cfg.ai.caption_model_lifecycle)
    except ValidationError:
        pass
```

`null` from the orchestrator → `None` in `OrchestratorAI` → no attempt to validate → `None` on `OpenAIConfig`. Clean path.

**`_build_app_config_v1`** — no changes. V1 payloads don't include lifecycle fields; `OpenAIConfig()` defaults both to `None`.

### Part D — Warning Emitter

New function `emit_model_lifecycle_warnings(openai_cfg: OpenAIConfig)` in `config/source.py` (or a new `config/lifecycle.py` if preferred):

```python
def emit_model_lifecycle_warnings(openai_cfg: OpenAIConfig) -> None:
    for role, lc in [("vision", openai_cfg.vision_model_lifecycle), ("caption", openai_cfg.caption_model_lifecycle)]:
        if lc is None:
            continue
        level = {"info": logging.INFO, "warning": logging.WARNING, "critical": logging.ERROR}.get(
            lc.severity, logging.WARNING
        )
        log_json(logger, level, "model_lifecycle_warning",
            model_role=role,
            warning=lc.warning,
            shutdown_date=lc.shutdown_date,
            recommended_replacement=lc.recommended_replacement,
            severity=lc.severity,
        )
```

**Call site**: invoke `emit_model_lifecycle_warnings(app_cfg.openai)` in `get_config()` after a successful fresh fetch (after `_build_app_config_v2` returns, before caching). This means:
- Warnings fire on every fresh config fetch (cache miss or TTL expiry)
- Warnings do NOT fire on cache hits (no spam per request)
- Standalone mode (`EnvConfigSource`): lifecycle fields are always `None`, so the emitter is a no-op if called

### Part E — Standalone Mode

No changes needed in `loader.py`. `OpenAIConfig()` already defaults both lifecycle fields to `None`. `EnvConfigSource.get_config()` does not call the emitter (or calls it, and it's a no-op).

### Part F — Tests

All tests in `publisher_v2/tests/test_model_lifecycle_warnings.py` (new file):

1. **`ModelLifecycle` model tests** — valid construction, severity validator rejects unknown values
2. **`OpenAIConfig` extension tests** — defaults to `None`, accepts valid `ModelLifecycle` instances
3. **`OrchestratorAI` parsing tests** — accepts lifecycle dicts, maps `null` to `None`, handles missing fields
4. **`_build_app_config_v2` mapping tests** — lifecycle dicts → `ModelLifecycle` on `OpenAIConfig`, malformed dict → `None` (no crash)
5. **Warning emitter tests** — correct log levels for each severity, no logs when both `None`, log content includes all required fields, no `credentials_ref` in log output
6. **Integration test** — `get_config()` fresh fetch with lifecycle data → warning emitted; cache hit → no warning

---

## Acceptance Criteria

### Model & Config (Parts A, B)

1. **AC-01**: `ModelLifecycle` is a Pydantic model with required fields `warning: str`, `shutdown_date: str`, `recommended_replacement: str`, `severity: str`. `ModelLifecycle(warning="deprecated_model", shutdown_date="2026-06-01", recommended_replacement="gpt-4o-2026-01", severity="warning")` constructs successfully.
2. **AC-02**: `ModelLifecycle(severity="unknown")` raises `ValidationError` (only `info`, `warning`, `critical` allowed).
3. **AC-03**: `OpenAIConfig()` has `vision_model_lifecycle=None` and `caption_model_lifecycle=None` by default.
4. **AC-04**: `OpenAIConfig(vision_model_lifecycle=ModelLifecycle(...))` stores the lifecycle object.

### Orchestrator Parsing (Part C)

5. **AC-05**: `OrchestratorAI.model_validate({"credentials_ref": "x", "vision_model": "gpt-4o", "vision_model_lifecycle": {"warning": "deprecated_model", "shutdown_date": "2026-06-01", "recommended_replacement": "gpt-4o-2026-01", "severity": "critical"}})` succeeds and `vision_model_lifecycle` is a dict.
6. **AC-06**: `OrchestratorAI.model_validate({"vision_model_lifecycle": null})` succeeds with `vision_model_lifecycle=None`.
7. **AC-07**: Given a schema v2 runtime payload where `ai.vision_model_lifecycle` is a valid dict and `ai.caption_model_lifecycle` is `null`, `_build_app_config_v2` produces `openai_cfg.vision_model_lifecycle` as a `ModelLifecycle` instance and `openai_cfg.caption_model_lifecycle` as `None`.
8. **AC-08**: Given a schema v2 runtime payload where `ai.vision_model_lifecycle` is a malformed dict (e.g., missing `severity`), `_build_app_config_v2` sets `openai_cfg.vision_model_lifecycle = None` (no crash, graceful degradation).
9. **AC-09**: Schema v1 parsing produces `openai_cfg.vision_model_lifecycle=None` and `openai_cfg.caption_model_lifecycle=None`.

### Warning Emitter (Part D)

10. **AC-10**: When `vision_model_lifecycle` has `severity="warning"`, `emit_model_lifecycle_warnings` emits a structured log at `logging.WARNING` level containing `model_role="vision"`, `warning`, `shutdown_date`, and `recommended_replacement`.
11. **AC-11**: When `caption_model_lifecycle` has `severity="critical"`, the emitter logs at `logging.ERROR` level with `model_role="caption"`.
12. **AC-12**: When `vision_model_lifecycle` has `severity="info"`, the emitter logs at `logging.INFO` level.
13. **AC-13**: When both lifecycle fields are `None`, the emitter produces zero log records.
14. **AC-14**: Log output from the emitter does not contain `credentials_ref`, `api_key`, or any other secret field.

### Cache Behavior

15. **AC-15**: `OrchestratorConfigSource.get_config()` calls `emit_model_lifecycle_warnings` after a fresh config fetch (cache miss). On a subsequent cache hit for the same host, no additional lifecycle warnings are emitted.

### Standalone Mode (Part E)

16. **AC-16**: In standalone mode (`EnvConfigSource`), `OpenAIConfig` has both lifecycle fields as `None`. No lifecycle warnings are emitted.

---

## Out of Scope

- **Admin UI banners**: Surfacing lifecycle warnings in the web admin UI is deferred to a future item. This item covers structured logging only.
- **Orchestrator API changes**: This is publisher-only consumption.
- **Automated model switching**: The publisher does not auto-switch models based on lifecycle data — it only warns.
- **`shutdown_date` format validation**: The publisher treats `shutdown_date` as an opaque string. The orchestrator is authoritative for format correctness.

## References

- [OpenAI API deprecations](https://platform.openai.com/docs/deprecations) — human source of truth for dates
- Orchestrator spec: `AI_02_OpenAiModelLifecycleMetadata.md`
- Paired orchestrator playbook: `PUB_05` (OpenAI runtime migration)

---

2026-03-16 — Spec hardened for Claude Code handoff
