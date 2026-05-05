# Implementation Handoff: PUB-043 — Orchestrator runtime — accept publisher type `email`

**Hardened:** 2026-05-05  
**Status:** Archived (delivered)  
**Tracking:** [GitHub #69](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/69)

## For Claude Code

### Test-first targets

| AC | Test file | Key test cases |
|----|-----------|----------------|
| AC1 | `publisher_v2/tests/config/test_orchestrator_runtime_config.py` | New async test: schema v2 JSON mirrors `test_parses_schema_v2` but publisher `type` is `"email"`; assert `email_enabled`, `email.recipient` / caption fields, `credentials_refs["smtp"] == "smtp-ref"`. |
| AC2 | `publisher_v2/tests/config/test_orchestrator_runtime_config.py` | Keep or tighten `test_parses_schema_v2`: still `type: fetlife`; assert `email_enabled` and `credentials_refs.get("smtp")` (add smtp assertion if missing). |
| AC3 | `publisher_v2/tests/config/test_orchestrator_runtime_config.py` | Payload with `type: email` and empty `recipient` (or missing `from_email` / `password_ref`); assert `email_enabled` is False and `"smtp" not in credentials_refs` (or smtp not set for that path). |
| AC4 | `publisher_v2/tests/config/test_orchestrator_runtime_config.py` | `type: email`, valid publisher config, omit `email_server` object from runtime `config`; assert `email_enabled` is False, no exception. |

### Mock boundaries

| External service | Mock strategy | Existing fixture |
|-----------------|---------------|------------------|
| Orchestrator HTTP | `httpx.MockTransport` handler for `/v1/runtime/by-host` + `/v1/credentials/resolve` | `_make_source()` in `test_orchestrator_runtime_config.py` |
| Env | `monkeypatch.setenv` for orchestrator + Dropbox app keys | Same as existing tests |

No live orchestrator, Dropbox, or SMTP.

### Files likely touched

| Area | Files to modify | Files to create |
|------|-----------------|-----------------|
| Config | `publisher_v2/src/publisher_v2/config/source.py` (`_build_app_config_v2` publisher loop) | — |
| Tests | `publisher_v2/tests/config/test_orchestrator_runtime_config.py` | — |

### Non-negotiables for this item

- [ ] Preview mode: N/A for this change (config parsing only; preview remains side-effect free per existing rules).
- [ ] Secrets: no hard-coded refs; only assert opaque refs from fixture JSON match expected keys.
- [ ] Auth: N/A (config layer).
- [ ] Coverage: ≥80% on affected modules (`source.py` branch for `email` type).

### Claude Code command

```text
/implement docs_v2/roadmap/archive/PUB-043_orchestrator-email-publisher-type.md
```
