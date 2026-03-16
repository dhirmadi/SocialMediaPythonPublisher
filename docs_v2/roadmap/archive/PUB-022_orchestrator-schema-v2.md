# PUB-022: Orchestrator Schema V2 Integration

| Field | Value |
|-------|-------|
| **ID** | PUB-022 |
| **Category** | Foundation |
| **Priority** | INF |
| **Effort** | XL |
| **Status** | Done |
| **Dependencies** | PUB-021 |

## Problem

Publisher V2 supported env-first standalone mode and partial orchestrator v1 mode (config.features + config.storage only). The orchestrator shipped schema v2 with expanded runtime config (publishers, email_server, ai, etc.) and multi-secret credential resolution. Publisher could not obtain per-tenant AI, publisher, or email config; could not resolve per-tenant OpenAI keys, Telegram tokens, or SMTP passwords; and query-string logging risk remained for runtime lookups.

## Desired Outcome

Integrate with orchestrator schema v2: parse all config blocks (`features`, `storage`, `publishers`, `email_server`, `ai`, `captionfile`, `confirmation`, `content`). Resolve credentials for `dropbox`, `openai`, `telegram`, `smtp` via `/v1/credentials/resolve`. Prefer POST for `/v1/runtime/by-host` to reduce query-string leakage. Clean ConfigSource abstraction (env-first vs orchestrator-sourced). No log leakage of credentials_ref, bearer tokens, or resolved secrets.

## Scope

- ConfigSource protocol: `EnvConfigSource`, `OrchestratorConfigSource`
- Schema v2 parsing with backward compatibility for schema v1
- Credential resolution for 4 providers; storage eager, AI/telegram/smtp lazy
- POST-preferred runtime lookup with GET fallback on 405
- In-memory credential cache (tenant, credentials_ref, version; TTL ≤10 min)
- Runtime config cache by normalized_host
- Single-flight pattern for credential resolution
- Tenant context via `request.state`; `/health/ready` checks orchestrator connectivity

## Acceptance Criteria

- AC1: Publisher V2 correctly parses orchestrator schema v2 responses including all config blocks
- AC2: Publisher V2 maintains backward compatibility with schema v1 responses
- AC3: Publisher V2 resolves credentials via `/v1/credentials/resolve` for dropbox, openai, telegram, smtp
- AC4: Credential resolution failures for optional features degrade gracefully; critical (dropbox) returns 503
- AC5: Publisher V2 uses POST for `/v1/runtime/by-host` by default, GET fallback on 405
- AC6: No credentials_ref, bearer tokens, or resolved secrets in logs
- AC7: Credentials cached in-memory with TTL ≤10 minutes
- AC8: Runtime config cached by normalized_host
- AC9: ConfigSource abstraction allows switching via configuration
- AC10: Service clients cached per-tenant, not per-request
- AC11: Env-first with `STANDALONE_HOST` rejects requests for other hosts
- AC12: Request context propagates tenant and services via `request.state`
- AC13: `/health/live` always 200; `/health/ready` checks orchestrator connectivity
- AC14: Single-flight pattern prevents thundering herd on credential resolution
- AC15: Storage credentials resolved eagerly; AI/telegram/smtp lazily

## Implementation Notes

- Reuse Pydantic models from Feature 021
- Async httpx for orchestrator HTTP calls; existing SanitizingFilter for log redaction
- Rollback: set `CONFIG_SOURCE=env` or unset `ORCHESTRATOR_BASE_URL`

## Related

- [Original feature doc](../../08_Epics/001_multi_tenant_orchestrator_runtime_config/022_orchestrator_schema_v2_integration/022_feature.md) — full historical detail
- `docs_v2/02_Specifications/ORCHESTRATOR_SERVICE_API_INTEGRATION_GUIDE.md`
