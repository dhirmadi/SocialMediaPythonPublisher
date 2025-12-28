# Change Request: Auth0 Dynamic Callback URL for Multi-Tenant

**CR ID:** CR-022-001  
**Feature:** 022 — Orchestrator Schema V2 Integration  
**Status:** Proposed  
**Date:** 2025-12-27  
**Author:** Product  
**Priority:** Must Fix (Blocks multi-tenant Auth0 login)

---

## Problem Statement

The current Auth0 configuration uses a **static callback URL** from environment variable:

```bash
AUTH0_CALLBACK_URL=https://fetlife-staging.shibari.photo/auth/callback
```

In multi-tenant mode, a single Publisher dyno serves multiple tenant domains:
- `tenant-a.shibari.photo`
- `tenant-b.shibari.photo`
- `tenant-c.shibari.photo`

**Problem:** A static callback URL causes Auth0 login to fail or redirect to the wrong tenant:
- User visits `tenant-a.shibari.photo` and clicks "Login"
- Auth0 redirects to the static callback: `fetlife-staging.shibari.photo/auth/callback`
- User ends up on wrong tenant or gets CORS/cookie errors

---

## Proposed Solution

### 1. Dynamic Callback URL Construction

Construct the Auth0 callback URL from the incoming request's `Host` header instead of using a static environment variable.

**Before:**
```python
callback_url = os.environ["AUTH0_CALLBACK_URL"]
```

**After:**
```python
def get_auth0_callback_url(request: Request) -> str:
    """Construct Auth0 callback URL dynamically from request host."""
    host = request.headers.get("host", "")
    # Normalize host (strip port if present for local dev)
    host = host.split(":")[0] if ":" in host else host
    scheme = request.url.scheme or "https"
    return f"{scheme}://{host}/auth/callback"
```

### 2. Auth0 Application Configuration

Register wildcard callback URLs in Auth0 Dashboard:

**Allowed Callback URLs:**
```
https://*.shibari.photo/auth/callback
```

Or for explicit registration (if wildcard not supported):
```
https://tenant-a.shibari.photo/auth/callback,
https://tenant-b.shibari.photo/auth/callback,
https://tenant-c.shibari.photo/auth/callback
```

### 3. Configuration Model Changes

**Remove from environment/orchestrator config:**
- `AUTH0_CALLBACK_URL` — no longer needed

**Keep in environment/orchestrator config:**
- `AUTH0_DOMAIN`
- `AUTH0_CLIENT_ID`
- `AUTH0_CLIENT_SECRET`
- `AUTH0_AUDIENCE` (optional)
- `ADMIN_LOGIN_EMAILS` / `AUTH0_ADMIN_EMAIL_ALLOWLIST`

**Callback path is constant:** `/auth/callback` — the host varies per request.

---

## Affected Components

### Publisher V2 Code Changes

| File | Change |
|------|--------|
| `publisher_v2/config/schema.py` | Remove `callback_url` from `Auth0Config` or make it optional/deprecated |
| `publisher_v2/config/loader.py` | Remove `AUTH0_CALLBACK_URL` requirement |
| `publisher_v2/web/auth.py` | Construct callback URL dynamically from request |
| `publisher_v2/web/app.py` | Update login/callback endpoints to use dynamic URL |

### Orchestrator Contract Changes

| Change | Details |
|--------|---------|
| Remove from runtime config | `auth0.callback_url` should not be in orchestrator response |
| Add to docs | Note that callback URL is constructed dynamically by Publisher |

### External Configuration

| System | Change |
|--------|--------|
| Auth0 Dashboard | Add wildcard `https://*.shibari.photo/auth/callback` to Allowed Callback URLs |
| Heroku Config Vars | Remove `AUTH0_CALLBACK_URL` (after code deployed) |

---

## Implementation Details

### Updated Auth0Config Schema

```python
class Auth0Config(BaseModel):
    """
    Configuration for Auth0 OIDC integration.
    Note: callback_url is constructed dynamically from request host.
    """
    domain: str = Field(..., description="Auth0 domain (e.g. tenant.auth0.com)")
    client_id: str = Field(..., description="Auth0 Client ID")
    client_secret: str = Field(..., description="Auth0 Client Secret")
    audience: Optional[str] = Field(default=None, description="Auth0 API Audience")
    admin_emails: str = Field(..., description="Comma-separated list of allowed emails")
    # REMOVED: callback_url — now constructed dynamically
```

### Updated Login Flow

```python
# In publisher_v2/web/auth.py

def build_auth0_authorize_url(request: Request, auth0_config: Auth0Config, state: str) -> str:
    """Build Auth0 authorization URL with dynamic callback."""
    # Construct callback URL from request host
    callback_url = get_auth0_callback_url(request)
    
    params = {
        "client_id": auth0_config.client_id,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
    }
    if auth0_config.audience:
        params["audience"] = auth0_config.audience
    
    return f"https://{auth0_config.domain}/authorize?" + urlencode(params)


def get_auth0_callback_url(request: Request) -> str:
    """Construct Auth0 callback URL dynamically from request host."""
    host = request.headers.get("host", "")
    # Strip port for local development (localhost:8000)
    if ":" in host and not host.startswith("["):  # Not IPv6
        host = host.split(":")[0]
    
    # Use HTTPS in production, allow HTTP for local dev
    scheme = "https"
    if host in ("localhost", "127.0.0.1"):
        scheme = request.url.scheme or "http"
    
    return f"{scheme}://{host}/auth/callback"
```

### Updated Token Exchange

```python
# In callback handler

async def auth0_callback(request: Request, code: str, state: str):
    """Handle Auth0 callback with dynamic redirect_uri."""
    # IMPORTANT: redirect_uri in token exchange must match authorize URL
    callback_url = get_auth0_callback_url(request)
    
    token_response = await exchange_code_for_tokens(
        auth0_domain=auth0_config.domain,
        client_id=auth0_config.client_id,
        client_secret=auth0_config.client_secret,
        code=code,
        redirect_uri=callback_url,  # Must match!
    )
    ...
```

---

## Testing Requirements

### Unit Tests

- [ ] `test_get_auth0_callback_url_production` — returns `https://tenant.shibari.photo/auth/callback`
- [ ] `test_get_auth0_callback_url_localhost` — returns `http://localhost/auth/callback`
- [ ] `test_get_auth0_callback_url_with_port` — strips port from host
- [ ] `test_build_auth0_authorize_url_uses_request_host`

### Integration Tests

- [ ] Login flow works for `tenant-a.shibari.photo`
- [ ] Login flow works for `tenant-b.shibari.photo`
- [ ] Callback redirects to correct tenant domain
- [ ] Admin cookie is set for correct domain

### Manual Testing

1. Configure Auth0 with wildcard callback URL
2. Deploy Publisher in multi-tenant mode
3. Login via `tenant-a.shibari.photo` → verify callback returns to `tenant-a`
4. Login via `tenant-b.shibari.photo` → verify callback returns to `tenant-b`
5. Verify admin session is isolated per tenant domain

---

## Rollout Plan

### Phase 1: Prepare Auth0
1. Add wildcard `https://*.shibari.photo/auth/callback` to Auth0 Allowed Callback URLs
2. Keep existing static callback URL temporarily (for rollback)

### Phase 2: Deploy Code
1. Deploy updated Publisher with dynamic callback URL construction
2. `AUTH0_CALLBACK_URL` env var is now ignored (backward compatible)

### Phase 3: Cleanup
1. Remove `AUTH0_CALLBACK_URL` from Heroku config vars
2. Remove old static callback URL from Auth0 (optional, doesn't hurt to keep)

---

## Rollback Plan

If issues arise:
1. Re-add `AUTH0_CALLBACK_URL` to environment
2. Revert code to use static callback URL
3. Static callback still registered in Auth0

---

## Acceptance Criteria

- [ ] Auth0 login works for any `*.shibari.photo` tenant domain
- [ ] Callback URL is constructed from request `Host` header
- [ ] `AUTH0_CALLBACK_URL` env var is no longer required
- [ ] Auth0Config schema updated (callback_url removed or deprecated)
- [ ] No cross-tenant session leakage
- [ ] Local development with `localhost` still works
- [ ] Unit tests cover dynamic URL construction
- [ ] Integration test verifies multi-tenant login flow

---

## Related

- Feature 022: Orchestrator Schema V2 Integration
- Feature 020: Auth0 Login
- Epic 001: Multi-Tenant Orchestrator Runtime Config

