# Story 06 — Tenant Context and Service Lifecycle

**Feature ID:** 022  
**Story ID:** 022-06  
**Status:** Shipped  
**Date:** 2025-12-25

---

## Context / Scope

Publisher V2 needs infrastructure for multi-tenant request handling:

1. **Tenant middleware** — Extract and validate host, resolve config
2. **Service factory** — Create and cache service clients per-tenant
3. **Health checks** — Liveness and readiness probes

This story implements the request lifecycle infrastructure that ties together Stories 01–05.

**Parent feature:** [022_feature.md](../../022_feature.md)  
**Depends on:** Story 01 (Config Source), Story 03 (Credential Resolution)

---

## Dependencies

| Story | Requirement |
|-------|-------------|
| 01 — Config Source Abstraction | `ConfigSource` and host normalization available |
| 03 — Credential Resolution | Credential resolution available for service client creation |

---

## Behaviour

### Preconditions

- Stories 01–03 are implemented
- FastAPI application structure exists

### Main Flow

#### 1. Tenant Middleware

Create middleware that runs on every request:

```python
@app.middleware("http")
async def tenant_middleware(request: Request, call_next):
    # Skip health endpoints
    if request.url.path.startswith("/health"):
        return await call_next(request)
    
    host = request.headers.get("host", "")
    config_source = get_config_source()
    
    try:
        # Normalize and validate host
        normalized = normalize_host(host)
        if not validate_host(normalized):
            return JSONResponse({"error": "Not found"}, status_code=404)
        
        # Get config (cached)
        tenant_config = await config_source.get_config(normalized)
        
        # Get or create services (cached per-tenant)
        services = await service_factory.get_services(tenant_config)
        
        # Inject into request state
        request.state.host = normalized
        request.state.tenant = tenant_config.tenant
        request.state.config = tenant_config.config
        request.state.services = services
        
    except TenantNotFoundError:
        return JSONResponse({"error": "Not found"}, status_code=404)
    except OrchestratorUnavailableError:
        return JSONResponse({"error": "Service unavailable"}, status_code=503)
    
    return await call_next(request)
```

#### 2. Service Factory

Create factory that manages tenant-scoped service clients:

```python
class TenantServiceFactory:
    """Factory for tenant-scoped service clients."""
    
    _cache: Dict[str, TenantServices]  # tenant -> services
    _max_size: int  # from TENANT_SERVICE_CACHE_MAX_SIZE
    
    async def get_services(self, tenant_config: TenantConfig) -> TenantServices:
        tenant = tenant_config.tenant
        
        # Check cache
        if tenant in self._cache:
            cached = self._cache[tenant]
            if not cached.is_expired():
                return cached
        
        # Create new services
        services = await self._create_services(tenant_config)
        
        # Cache with LRU eviction
        if len(self._cache) >= self._max_size:
            self._evict_lru()
        self._cache[tenant] = services
        
        return services
    
    async def _create_services(self, tenant_config: TenantConfig) -> TenantServices:
        config_source = get_config_source()
        
        # Resolve storage credential (eager)
        storage_cred = await config_source.get_credentials(
            tenant_config.host,
            tenant_config.credentials_refs["storage"]
        )
        
        # Create Dropbox client
        storage = DropboxStorageService(
            refresh_token=storage_cred.refresh_token,
            app_key=os.environ["DROPBOX_APP_KEY"],
            app_secret=os.environ["DROPBOX_APP_SECRET"],
            paths=tenant_config.config.storage.paths,
        )
        
        # Other services created lazily
        return TenantServices(
            storage=storage,
            ai=LazyService(lambda: self._create_ai_service(tenant_config)),
            telegram=LazyService(lambda: self._create_telegram_service(tenant_config)),
            email=LazyService(lambda: self._create_email_service(tenant_config)),
        )
```

#### 3. Tenant Services Container

```python
@dataclass
class TenantServices:
    """Container for tenant-scoped services."""
    storage: StorageService
    ai: LazyService[AIService]
    telegram: LazyService[TelegramService]
    email: LazyService[EmailService]
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    ttl_seconds: int = 600  # from config
    
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.created_at + timedelta(seconds=self.ttl_seconds)


class LazyService(Generic[T]):
    """Lazy service wrapper - creates service on first access."""
    
    def __init__(self, factory: Callable[[], Awaitable[T]]):
        self._factory = factory
        self._instance: T | None = None
        self._error: Exception | None = None
    
    async def get(self) -> T | None:
        if self._instance is not None:
            return self._instance
        if self._error is not None:
            return None  # Already failed, don't retry
        
        try:
            self._instance = await self._factory()
            return self._instance
        except CredentialResolutionError as e:
            self._error = e
            logger.warning(f"Service unavailable: {e}")
            return None
```

#### 4. Health Checks

```python
@app.get("/health/live")
async def health_live():
    """Liveness probe - always returns 200 if process is running."""
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready():
    """Readiness probe - checks external dependencies."""
    config_source = get_config_source()
    
    if not config_source.is_orchestrated():
        # Env-first mode: always ready
        return {"status": "ok", "mode": "standalone"}
    
    # Orchestrator mode: check connectivity
    try:
        # Use a lightweight check (e.g., cached config exists or can fetch)
        await config_source.check_connectivity()
        return {"status": "ok", "mode": "orchestrated"}
    except OrchestratorUnavailableError:
        return JSONResponse(
            {"status": "not_ready", "reason": "orchestrator_unavailable"},
            status_code=503
        )
```

### Configuration Options

| Env var | Default | Description |
|---------|---------|-------------|
| `TENANT_SERVICE_CACHE_MAX_SIZE` | 1000 | Max cached tenant service sets |
| `TENANT_SERVICE_TTL_SECONDS` | 600 | TTL for cached tenant services |

### Alternative Flows

- **Env-first mode**: Middleware skips tenant extraction, uses singleton services
- **Health check bypass**: `/health/*` endpoints skip tenant middleware

### Error Flows

- **Invalid host**: Return 404 (via `validate_host()`)
- **Tenant not found**: Return 404 (via orchestrator 404)
- **Orchestrator unavailable**: Return 503 (safe failure)
- **Service creation failure**: Return 503 with error logged

---

## Acceptance Criteria

- [ ] Tenant middleware extracts host and resolves config on every request
- [ ] Middleware skips `/health/*` endpoints
- [ ] Invalid hosts return 404 without calling orchestrator
- [ ] `request.state.tenant`, `request.state.config`, `request.state.services` are populated
- [ ] Service factory caches services per-tenant with LRU eviction
- [ ] Service factory respects `TENANT_SERVICE_CACHE_MAX_SIZE`
- [ ] Storage service created eagerly; AI/telegram/email created lazily
- [ ] Lazy service creation failures are logged but don't crash request
- [ ] `/health/live` always returns 200
- [ ] `/health/ready` returns 200 in env-first mode
- [ ] `/health/ready` returns 503 if orchestrator unreachable in orchestrator mode
- [ ] Unit tests cover middleware, factory, and health checks

---

## Testing

### Manual Testing

1. Start in env-first mode → verify middleware populates request state
2. Start in orchestrator mode → verify config fetched from orchestrator
3. Send request with invalid host → verify 404 response
4. Stop orchestrator → verify `/health/ready` returns 503
5. Verify `/health/live` returns 200 even when orchestrator down

### Automated Tests

Add tests under `publisher_v2/tests/web/`:

- `test_tenant_middleware.py`:
  - `test_middleware_extracts_host_and_tenant`
  - `test_middleware_skips_health_endpoints`
  - `test_middleware_returns_404_for_invalid_host`
  - `test_middleware_returns_503_on_orchestrator_failure`
  - `test_middleware_populates_request_state`

- `test_service_factory.py`:
  - `test_factory_creates_services_for_new_tenant`
  - `test_factory_returns_cached_services`
  - `test_factory_evicts_lru_when_max_size_reached`
  - `test_factory_creates_storage_eagerly`
  - `test_factory_creates_ai_lazily`
  - `test_lazy_service_handles_creation_failure`

- `test_health_endpoints.py`:
  - `test_liveness_always_returns_200`
  - `test_readiness_returns_200_in_env_mode`
  - `test_readiness_returns_503_when_orchestrator_down`

---

## Implementation Notes

### Files to Create/Modify

- **Create**: `publisher_v2/src/publisher_v2/web/middleware.py`
  - `tenant_middleware()`
  - Host extraction and validation

- **Create**: `publisher_v2/src/publisher_v2/services/factory.py`
  - `TenantServiceFactory`
  - `TenantServices`
  - `LazyService`

- **Create**: `publisher_v2/src/publisher_v2/web/health.py`
  - `/health/live`
  - `/health/ready`

- **Modify**: `publisher_v2/src/publisher_v2/web/app.py`
  - Register middleware
  - Register health routes

### Request State Access Pattern

Route handlers access tenant context via `request.state`:

```python
@app.get("/api/images")
async def list_images(request: Request):
    storage = request.state.services.storage
    return await storage.list_images()

@app.post("/api/analyze")
async def analyze_image(request: Request, image_id: str):
    ai = await request.state.services.ai.get()
    if ai is None:
        raise HTTPException(503, "AI service unavailable")
    return await ai.analyze(image_id)
```

### Repo Rules

- **Async hygiene**: All middleware and factory methods are async
- **Safe failure**: Service creation failures don't crash; features degrade
- **No secrets in logs**: Credential resolution errors logged without secrets

---

## Change History

| Date | Change |
|------|--------|
| 2025-12-25 | Initial story draft (from PM decision on review issue #41) |

