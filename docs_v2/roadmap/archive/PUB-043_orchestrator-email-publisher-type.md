# PUB-043: Orchestrator runtime — accept publisher type `email` for FetLife-style email

| Field | Value |
|-------|-------|
| **ID** | PUB-043 |
| **Category** | Config |
| **Priority** | P0 |
| **Effort** | S |
| **Status** | Done |
| **Dependencies** | PUB-022 |
| **Tracking** | [GitHub #69](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/69) |

## Problem

The platform orchestrator persists FetLife-style email publishers with `"type": "email"` (canonical). Publisher V2 `_build_app_config_v2` only enters the shared-`email_server` branch when `p.type == "fetlife"`. Tenants whose runtime JSON lists `email` never get `platforms.email_enabled`, `EmailConfig`, or `creds_refs["smtp"]`, so parallel publish sees no enabled email publisher even when `email_server` and `password_ref` are present.

## Desired Outcome

Treat publisher type `email` the same as `fetlife` when building email platform state from schema v2: same preconditions (enabled publisher, `email_server`, recipient, `from_email`, `password_ref`), same `EmailConfig` and `creds_refs["smtp"]` registration. Preserve `fetlife` as a legacy alias; both types must share one code path.

## Scope

**In scope**

- `publisher_v2/src/publisher_v2/config/source.py` — `_build_app_config_v2` publisher loop: extend the condition that gates the FetLife-style email block so it matches `p.type in ("fetlife", "email")` (or equivalent single branch).
- Tests in `publisher_v2/tests/config/test_orchestrator_runtime_config.py` (or adjacent config tests): runtime payload with `"type": "email"` proves email is enabled and SMTP ref is wired.

**Out of scope**

- Orchestrator API or OpenAI / PLT_10 changes (other repos).
- Generic SMTP publishers with different config shapes than the existing FetLife-style block (only parity for `email` vs `fetlife`).

## Acceptance Criteria

- **AC1**: Given an orchestrator schema v2 runtime payload identical to an otherwise-valid FetLife email setup except the publisher entry has `"type": "email"` (not `"fetlife"`), when `OrchestratorConfigSource.get_config` completes successfully, then `resolved.config.platforms.email_enabled` is `True`, `resolved.config.email` is non-`None` with the same recipient and caption fields as today’s `fetlife` path, and `resolved.credentials_refs` contains key `"smtp"` equal to `config.email_server.password_ref`.
- **AC2**: Given the same payload as today’s tests with `"type": "fetlife"` and a valid `email_server`, behavior after the change remains unchanged: `email_enabled` is `True` and `credentials_refs["smtp"]` is set (regression guard).
- **AC3**: Given an enabled publisher with `"type": "email"` but `config.recipient` missing or blank, or `email_server.from_email` missing, or `email_server.password_ref` missing, when `get_config` completes, then `platforms.email_enabled` is `False` and no `smtp` credential ref is added for that publisher (same failure semantics as the current `fetlife` branch).
- **AC4**: Given an enabled publisher with `"type": "email"` and valid email fields, but `email_server` is absent from the runtime config, when `get_config` completes, then `platforms.email_enabled` is `False` (no crash; same as `fetlife` when `email_server` is missing).

## Implementation Notes

- Orchestrator reference: `upsert_email_publisher` sets `"type": "email"`.
- Prefer a named constant or tuple for allowed types if the project already uses that pattern; otherwise inline `("fetlife", "email")` next to the existing check.
- Preview mode: unchanged — this item only affects config resolution from orchestrator, not publish side effects.

## Related

- PUB-022 (orchestrator schema v2)
- [GitHub #69](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/69)

---

_2026-05-05 — Spec hardened for Claude Code handoff (GitHub #69)._  
_2026-05-05 — Archived (delivered, verified)._
