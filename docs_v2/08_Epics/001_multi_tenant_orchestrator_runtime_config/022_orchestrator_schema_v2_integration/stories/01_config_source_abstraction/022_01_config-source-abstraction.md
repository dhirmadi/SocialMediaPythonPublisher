# Story 01 — Config Source Abstraction

**Feature ID:** 022  
**Story ID:** 022-01  
**Status:** Shipped  
**Date:** 2025-12-25

---

## Context / Scope

Publisher V2 needs to support two configuration sources:

1. **Env-first mode** (Feature 021) — Configuration loaded from JSON environment variables
2. **Orchestrator mode** — Configuration fetched from platform-orchestrator via service API

This story creates a `ConfigSource` abstraction that allows clean switching between these modes without changing downstream code.

**Parent feature:** [022_feature.md](../../022_feature.md)

---

## Multi-Tenant Request Flow Architecture

### Request Lifecycle (Orchestrator Mode)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Incoming Request                                   │
│                    Host: xxx.shibari.photo                                  │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. Middleware: Extract & Validate Host                                       │
│    - normalize_host("xxx.shibari.photo") → "xxx.shibari.photo"              │
│    - validate_host() → True                                                  │
│    - Store host in request.state.host                                       │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. Config Resolution (per-request, cached)                                   │
│    config_source.get_config(host="xxx.shibari.photo")                       │
│    - Check runtime config cache → hit? return cached                        │
│    - Miss? Call orchestrator → cache result                                 │
│    - Returns TenantConfig { tenant="xxx", config=..., credentials_refs=... }│
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. Service Factory: Get or Create Tenant Services                            │
│    service_factory.get_services(tenant_config)                              │
│    - Check service cache for tenant → hit? return cached services           │
│    - Miss? Resolve credentials, create clients, cache by tenant             │
│    - Returns TenantServices { storage, ai, publishers, email }              │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. Request Handler: Execute with Tenant Context                              │
│    - request.state.tenant = tenant_config.tenant                            │
│    - request.state.services = tenant_services                               │
│    - Handle request using tenant-scoped services                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Service Client Lifecycle

**Decision:** Cache service clients per-tenant with TTL-based invalidation.

| Component | Lifecycle | Cache Key | Invalidation |
|-----------|-----------|-----------|--------------|
| Runtime config | Per-request (cached) | `host` | TTL from orchestrator |
| Credentials | Per-tenant (cached) | `(tenant, credentials_ref, version)` | TTL or version change |
| Dropbox client | Per-tenant (cached) | `tenant` | When credentials change |
| OpenAI client | Per-tenant (cached) | `tenant` | When credentials change |
| Telegram bot | Per-tenant (cached) | `tenant` | When credentials change |
| SMTP client | Per-tenant (cached) | `tenant` | When credentials change |

**Rationale:**
- Creating clients per-request would be too slow (connection overhead)
- Caching per-tenant amortizes connection setup across requests
- Credential version tracking ensures clients are refreshed when secrets rotate

### Request Context (FastAPI)

Tenant context is propagated via `request.state`:

```python
# Middleware sets:
request.state.host = normalized_host
request.state.tenant = tenant_config.tenant
request.state.services = tenant_services

# Route handlers access:
@app.get("/api/images")
async def list_images(request: Request):
    storage = request.state.services.storage
    return await storage.list_images()
```

---

## Behaviour

### Preconditions

- Feature 021 (config env consolidation) is shipped
- Existing Pydantic models for config sections exist in `publisher_v2/src/publisher_v2/config/`

### Main Flow

1. Define a `ConfigSource` protocol (or ABC) with **async** methods:
   - `async get_config(host: str | None) -> TenantConfig`
   - `async get_credentials(host: str, credentials_ref: str) -> CredentialPayload`
   - `is_orchestrated() -> bool` (sync, no I/O)

   > **Note**: Methods accept `host` (not tenant) since that's what we have at request time. Tenant is extracted internally using `extract_tenant(host, base_domain)`.

   The returned `TenantConfig` wraps:
   - `tenant: str` — extracted tenant identifier
   - `config: ApplicationConfig` — the actual configuration
   - `credentials_refs: dict[str, str]` — mapping of credential refs to resolve later

2. Implement `EnvConfigSource`:
   - Wraps existing `load_application_config()` from Feature 021
   - **Single-tenant safety**: If `STANDALONE_HOST` is set, reject requests where `host ≠ STANDALONE_HOST`
   - If `STANDALONE_HOST` is not set, allow any host (backward compatible, but logs warning on first multi-tenant access)
   - Returns a synthetic `TenantConfig` with `tenant="default"` (or extracted from `STANDALONE_HOST`)
   - `get_credentials()` returns credentials from flat env vars
   - `is_orchestrated()` returns `False`

3. Implement `OrchestratorConfigSource` (skeleton):
   - Accepts `ORCHESTRATOR_BASE_URL`, `ORCHESTRATOR_SERVICE_TOKEN`, and `ORCHESTRATOR_BASE_DOMAIN`
   - `ORCHESTRATOR_BASE_DOMAIN` defaults to `shibari.photo` if not set
   - `get_config()` calls runtime endpoint (implementation in Story 02)
   - `get_credentials()` calls credentials endpoint (implementation in Story 03)
   - `is_orchestrated()` returns `True`

4. Create factory function `get_config_source() -> ConfigSource`:
   - If `ORCHESTRATOR_BASE_URL` is set → return `OrchestratorConfigSource`
   - Else → return `EnvConfigSource`

5. Update web service initialization (`publisher_v2/web/service.py`) to use the factory.

### Alternative Flows

- **ENV override**: If `CONFIG_SOURCE=env` is explicitly set, always use `EnvConfigSource` regardless of `ORCHESTRATOR_BASE_URL` (escape hatch)

### Error Flows

- Missing `ORCHESTRATOR_SERVICE_TOKEN` when `ORCHESTRATOR_BASE_URL` is set → raise `ConfigurationError` at startup
- In env-first mode with `STANDALONE_HOST` set: request for different host → return 404 (tenant not found)
- In env-first mode without `STANDALONE_HOST`: multi-tenant request → log warning, return config (backward compat but risky)

### Configuration Options

| Env var | Required | Default | Description |
|---------|----------|---------|-------------|
| `ORCHESTRATOR_BASE_URL` | No | — | Base URL for orchestrator API (e.g., `https://orchestrator.shibari.photo`) |
| `ORCHESTRATOR_SERVICE_TOKEN` | If `BASE_URL` set | — | Bearer token for service-to-service auth |
| `ORCHESTRATOR_BASE_DOMAIN` | No | `shibari.photo` | Base domain for tenant host construction |
| `CONFIG_SOURCE` | No | — | Set to `env` to force env-first mode |
| `STANDALONE_HOST` | No | — | In env-first mode, only allow this host (tenant isolation) |

---

## Host Normalization

Before calling the orchestrator API, Publisher must normalize the incoming request host per the contract:

### Normalization Rules

1. **Lowercase** the host
2. **Strip port** (e.g., `tenant.shibari.photo:8080` → `tenant.shibari.photo`)
3. **Strip trailing dot** (e.g., `tenant.shibari.photo.` → `tenant.shibari.photo`)
4. **Trim whitespace** — leading/trailing whitespace is invalid

### Invalid Host Shapes (Reject Without Calling Orchestrator)

These should return a 404-equivalent response immediately:

- IPv4 literals (e.g., `127.0.0.1`)
- IPv6 literals (e.g., `::1`, `[::1]`)
- `localhost`
- `www.*` prefixed hosts
- Double-dot / empty label (e.g., `tenant..shibari.photo`)

### Tenant Extraction

For hosts of the form `<tenant>.<base-domain>`:
- Extract tenant as the **first label** (e.g., `xxx.shibari.photo` → tenant is `xxx`)

---

## Acceptance Criteria

- [ ] `ConfigSource` protocol is defined with async `get_config(host)`, async `get_credentials(host, ref)`, and sync `is_orchestrated()` methods
- [ ] `TenantConfig` dataclass wraps tenant identifier, config, and credentials_refs
- [ ] `EnvConfigSource` wraps existing loader and returns config from environment variables
- [ ] `EnvConfigSource.get_credentials()` returns credentials from flat env vars (`TELEGRAM_BOT_TOKEN`, `EMAIL_PASSWORD`, `OPENAI_API_KEY`, `DROPBOX_REFRESH_TOKEN`)
- [ ] `OrchestratorConfigSource` skeleton is created (actual API calls in Stories 02–03)
- [ ] Factory function selects source based on `ORCHESTRATOR_BASE_URL` presence
- [ ] `CONFIG_SOURCE=env` forces env-first mode as escape hatch
- [ ] `ORCHESTRATOR_BASE_DOMAIN` defaults to `shibari.photo` when not set
- [ ] `STANDALONE_HOST` restricts env-first mode to single host (returns 404 for others)
- [ ] Web service initialization uses the factory
- [ ] Middleware extracts host and stores in `request.state`
- [ ] Service factory caches clients per-tenant
- [ ] Host normalization is implemented (lowercase, strip port, strip trailing dot)
- [ ] Invalid host shapes (IPv4, IPv6, localhost, www.*, double-dot) are rejected without calling orchestrator
- [ ] Unit tests cover factory selection logic
- [ ] Unit tests cover host normalization and rejection of invalid shapes

---

## Testing

### Manual Testing

1. Start Publisher with only env vars (no `ORCHESTRATOR_BASE_URL`) → verify config loads from env
2. Set `ORCHESTRATOR_BASE_URL` but not `ORCHESTRATOR_SERVICE_TOKEN` → verify startup fails with clear error
3. Set both `ORCHESTRATOR_BASE_URL` and `ORCHESTRATOR_SERVICE_TOKEN` → verify `OrchestratorConfigSource` is selected
4. Set `CONFIG_SOURCE=env` with `ORCHESTRATOR_BASE_URL` set → verify `EnvConfigSource` is used

### Automated Tests

Add/extend tests under `publisher_v2/tests/config/`:

- `test_config_source_factory.py`:
  - `test_factory_returns_env_source_when_orchestrator_url_not_set`
  - `test_factory_returns_orchestrator_source_when_url_set`
  - `test_factory_returns_env_source_when_config_source_env_override`
  - `test_factory_raises_when_url_set_but_token_missing`
- `test_env_config_source.py`:
  - `test_get_config_loads_from_env`
  - `test_get_credentials_returns_env_secrets`
  - `test_is_orchestrated_returns_false`
  - `test_standalone_host_rejects_other_hosts`
  - `test_standalone_host_allows_matching_host`
  - `test_no_standalone_host_logs_warning_on_multi_tenant`
- `test_host_normalization.py`:
  - `test_normalize_host_lowercase`
  - `test_normalize_host_strips_port`
  - `test_normalize_host_strips_trailing_dot`
  - `test_reject_ipv4_literal`
  - `test_reject_ipv6_literal`
  - `test_reject_localhost`
  - `test_reject_www_prefix`
  - `test_reject_double_dot`
  - `test_extract_tenant_from_host`

---

## Implementation Notes

### Files to Create/Modify

- **Create**: `publisher_v2/src/publisher_v2/config/source.py`
  - `ConfigSource` protocol
  - `EnvConfigSource` class
  - `OrchestratorConfigSource` skeleton
  - `get_config_source()` factory

- **Create**: `publisher_v2/src/publisher_v2/config/host_utils.py`
  - `normalize_host(host: str) -> str` — applies normalization rules
  - `validate_host(host: str) -> bool` — returns False for invalid shapes
  - `extract_tenant(host: str, base_domain: str) -> str` — extracts tenant label

- **Modify**: `publisher_v2/src/publisher_v2/web/service.py`
  - Use `get_config_source()` instead of direct `load_application_config()` call

### Credential Handling in EnvConfigSource

In env-first mode, credentials are loaded directly from environment variables. The `credentials_ref` parameter is **ignored** — credentials are looked up by provider type inferred from context:

| Context | Env var |
|---------|---------|
| Storage (Dropbox) | `DROPBOX_REFRESH_TOKEN` |
| AI (OpenAI) | `OPENAI_API_KEY` |
| Publisher (Telegram) | `TELEGRAM_BOT_TOKEN` |
| Email (SMTP) | `EMAIL_PASSWORD` |

This maintains backward compatibility with Feature 021's flat env var approach.

### Repo Rules

- No secrets in code or logs
- Async hygiene: this story is mostly sync (factory/initialization), but `OrchestratorConfigSource` methods will be async in Stories 02–03

---

### Host Normalization Implementation Sketch

```python
import re

def normalize_host(host: str) -> str:
    """Normalize host per orchestrator contract."""
    h = host.lower().strip()
    # Strip port
    h = re.sub(r':\d+$', '', h)
    # Strip trailing dot
    h = h.rstrip('.')
    return h

def validate_host(host: str) -> bool:
    """Return False for invalid host shapes."""
    h = normalize_host(host)
    
    # Reject IPv4 literals
    if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', h):
        return False
    
    # Reject IPv6 literals
    if h.startswith('[') or '::' in h or re.match(r'^[0-9a-f:]+$', h):
        return False
    
    # Reject localhost
    if h == 'localhost':
        return False
    
    # Reject www prefix
    if h.startswith('www.'):
        return False
    
    # Reject double-dot / empty label
    if '..' in h or h.startswith('.') or h.endswith('.'):
        return False
    
    return True

def extract_tenant(host: str, base_domain: str = "shibari.photo") -> str:
    """Extract tenant label from host.
    
    Args:
        host: Normalized host (e.g., "xxx.shibari.photo")
        base_domain: Base domain from ORCHESTRATOR_BASE_DOMAIN env var
    """
    h = normalize_host(host)
    if h.endswith('.' + base_domain):
        return h[:-len(base_domain) - 1].split('.')[0]
    return h.split('.')[0]
```

---

## Change History

| Date | Change |
|------|--------|
| 2025-12-24 | Initial story draft |
| 2025-12-25 | Added host normalization requirements and validation rules |
| 2025-12-25 | Q1: Added `ORCHESTRATOR_BASE_DOMAIN` env var with default |
| 2025-12-25 | Q2: Changed interface from `tenant` to `host` parameter |
| 2025-12-25 | Q3/Q4: Added multi-tenant request flow architecture and service client lifecycle |
| 2025-12-25 | Q5: Added `ENV_ALLOWED_TENANT` for env-first tenant isolation |

