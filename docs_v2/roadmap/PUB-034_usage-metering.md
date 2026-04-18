# PUB-034: Usage Metering — Report Billable AI Consumption to Orchestrator

| Field | Value |
|-------|-------|
| **ID** | PUB-034 |
| **Category** | Foundation |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Hardened |
| **Dependencies** | Orchestrator roadmap #14 (shipped) |
| **GitHub Issue** | #57 |

## Problem

The platform orchestrator has shipped usage ingest and credential entitlements (orchestrator roadmap #14). Metering is **push-based**: the publisher must call `POST /v1/billing/usage` after billable work completes. Today, the publisher's `OrchestratorClient` has no method for this endpoint, and no workflow hooks emit usage events. Consequences:

1. **Wallet debits never occur** for real publisher-driven consumption — the commercial model doesn't function.
2. **Entitlement gates** on `resolve_credentials` (403 when workspace can't afford platform-billed providers) are under-fed in practice.
3. The 403 response from `resolve_credentials` is ambiguous — it could mean "bad token" or "out of credits", but the publisher reports both as `CredentialResolutionError("Orchestrator authorization failed (403)")`.

## Desired Outcome

After any successful OpenAI API call (vision analysis or caption generation), the publisher emits a usage event to the orchestrator with the token count consumed. The orchestrator records the usage, debits the workspace wallet, and the entitlement gate on credential resolution works end-to-end. Standalone (non-orchestrator) mode is unaffected.

---

## Part A — `OrchestratorClient.post_usage()` method

**File**: `publisher_v2/src/publisher_v2/config/orchestrator_client.py`

Add a new method to `OrchestratorClient`:

```python
async def post_usage(
    self,
    *,
    tenant_id: str,
    metric: str,
    quantity: int,
    unit: str,
    idempotency_key: str,
    occurred_at: str,
    source: str = "publisher",
    request_id: str | None = None,
) -> dict[str, Any]:
```

**Behavior**:

- Calls `POST {self._base_url}/v1/billing/usage` with JSON body containing all parameters.
- Headers: `Authorization: Bearer {self._token}` via `self._headers(request_id=request_id)`. No `X-Tenant` header — `tenant_id` is in the body.
- Uses existing `_request_with_retry` for retries on 429/5xx.
- Response handling:
  - **200**: return `resp.json()` (includes duplicate idempotency — no second debit, treated as success).
  - **403**: raise `CredentialResolutionError("Orchestrator authorization failed (403)")` (same as `resolve_credentials` — bad service token).
  - **404**: raise `UsageMeteringError("Tenant not found for usage reporting")`.
  - **422**: raise `UsageMeteringError(f"Usage rejected (422): invalid body or unknown metric '{metric}'")`.
  - **5xx after retry exhaustion**: raised by `_request_with_retry` as `OrchestratorUnavailableError`.

**New exception** in `publisher_v2/core/exceptions.py`:

```python
class UsageMeteringError(SocialMediaPublisherError):
    """Usage metering ingest call failed (non-retryable)."""
```

### Acceptance Criteria

- **AC-A1**: `post_usage()` sends `POST /v1/billing/usage` with JSON body `{"tenant_id", "source", "idempotency_key", "metric", "quantity", "unit", "occurred_at"}` and `Authorization: Bearer` header.
- **AC-A2**: 200 response returns parsed JSON dict without raising.
- **AC-A3**: Duplicate `idempotency_key` (200 response) is treated as success — no exception raised.
- **AC-A4**: 422 response raises `UsageMeteringError` with the metric name in the message.
- **AC-A5**: 403 response raises `CredentialResolutionError`.
- **AC-A6**: 404 response raises `UsageMeteringError`.
- **AC-A7**: 5xx after retry exhaustion raises `OrchestratorUnavailableError` (existing behavior from `_request_with_retry`).

---

## Part B — Return token usage from AI methods

The OpenAI Python SDK response object has `resp.usage.total_tokens` (int) and `resp.id` (str). Currently the AI methods discard both. They need to surface them so the caller can emit metering.

**Approach**: Add a `@dataclass` to carry usage metadata alongside the normal return value. Define in `publisher_v2/core/models.py`:

```python
@dataclass
class AIUsage:
    response_id: str
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
```

**Changes to `publisher_v2/services/ai.py`**:

Each low-level method (`analyze`, `generate`, `generate_with_sd`, `generate_multi`, `generate_multi_with_sd`) must extract `resp.usage` and `resp.id` and return an `AIUsage` alongside its normal return value. The cleanest pattern: each method returns a tuple `(result, AIUsage | None)`.

- `VisionAnalyzerOpenAI.analyze()` → returns `tuple[ImageAnalysis, AIUsage | None]`
- `CaptionGeneratorOpenAI.generate()` → returns `tuple[str, AIUsage | None]`
- `CaptionGeneratorOpenAI.generate_with_sd()` → returns `tuple[dict[str, str], AIUsage | None]`
- `CaptionGeneratorOpenAI.generate_multi()` → returns `tuple[dict[str, str], AIUsage | None]`
- `CaptionGeneratorOpenAI.generate_multi_with_sd()` → returns `tuple[dict[str, str], AIUsage | None]`

**Extracting usage from OpenAI response** — add a helper:

```python
def _extract_usage(resp: Any) -> AIUsage | None:
    if resp.usage is None:
        return None
    return AIUsage(
        response_id=resp.id or "",
        total_tokens=resp.usage.total_tokens or 0,
        prompt_tokens=resp.usage.prompt_tokens or 0,
        completion_tokens=resp.usage.completion_tokens or 0,
    )
```

`resp.usage` can be `None` if the API returns no usage data (e.g. certain streaming modes or test doubles). Always return `None` in that case — the metering layer skips emission when `AIUsage` is `None`.

**`AIService` wrapper methods** must aggregate usage from both analyze and caption calls, returning a list of `AIUsage` alongside the normal result. The caller collects all usage entries and emits them. Define in `AIService`:

```python
async def create_caption_pair_from_analysis(
    self, analysis: ImageAnalysis, spec: CaptionSpec
) -> tuple[str, str | None, list[AIUsage]]:
```

(Similarly for `create_multi_caption_pair_from_analysis` and other public methods.)

### Acceptance Criteria

- **AC-B1**: `AIUsage` dataclass exists in `publisher_v2/core/models.py` with fields `response_id: str`, `total_tokens: int`, `prompt_tokens: int`, `completion_tokens: int`.
- **AC-B2**: `VisionAnalyzerOpenAI.analyze()` returns `tuple[ImageAnalysis, AIUsage | None]`. When `resp.usage` is not `None`, the `AIUsage` contains the correct token counts and `resp.id`.
- **AC-B3**: All four `CaptionGeneratorOpenAI` generation methods return `tuple[<original_return_type>, AIUsage | None]`.
- **AC-B4**: When `resp.usage` is `None` (e.g. test double), `AIUsage` is `None` — no crash.
- **AC-B5**: `AIService` public methods (`create_caption_pair_from_analysis`, `create_multi_caption_pair_from_analysis`) aggregate and return a `list[AIUsage]` alongside their normal return values.
- **AC-B6**: `NullAIService` methods (if invoked despite the guard) return empty usage lists — no exceptions.
- **AC-B7**: Existing callers in `WorkflowOrchestrator.execute()` and `WebImageService.analyze_and_caption()` are updated to accept the new return signatures.

---

## Part C — Emit usage in orchestrated callers

**Where tenant context is available**:

- `WebImageService` has `self._runtime.tenant` (str) and `self._config_source._client` (the `OrchestratorClient`). But `_client` is a private attribute of `OrchestratorConfigSource`.
- `WorkflowOrchestrator` has **no** tenant or client reference — it receives `config`, `storage`, `ai_service`, `publishers`.

**Design decision**: Add an optional `UsageMeter` collaborator that encapsulates the orchestrator client + tenant. Inject it where available; when absent (standalone mode), metering is a no-op.

**New class** in `publisher_v2/services/usage_meter.py`:

```python
class UsageMeter:
    def __init__(self, client: OrchestratorClient, tenant_id: str) -> None:
        self._client = client
        self._tenant_id = tenant_id
        self._logger = logging.getLogger("publisher_v2.metering")

    async def emit(self, usage: AIUsage, metric: str = "ai_tokens", unit: str = "tokens") -> None:
        """Fire-and-forget usage emission. Never raises."""
        try:
            await self._client.post_usage(
                tenant_id=self._tenant_id,
                metric=metric,
                quantity=usage.total_tokens,
                unit=unit,
                idempotency_key=usage.response_id,
                occurred_at=datetime.now(timezone.utc).isoformat(),
                source="publisher",
            )
        except Exception:
            log_json(
                self._logger, logging.WARNING, "usage_metering_failed",
                metric=metric, quantity=usage.total_tokens,
                tenant_id=self._tenant_id,
            )

    async def emit_all(self, usages: list[AIUsage], metric: str = "ai_tokens", unit: str = "tokens") -> None:
        for u in usages:
            if u is not None and u.total_tokens > 0:
                await self.emit(u, metric=metric, unit=unit)
```

**Integration points**:

1. **`WebImageService`**: In `__init__` (orchestrated path), construct a `UsageMeter` from `self._config_source._client` and `self._runtime.tenant`. Store as `self._usage_meter: UsageMeter | None`. In `analyze_and_caption()`, after AI calls return usage, call `await self._usage_meter.emit_all(usages)`.

2. **`WorkflowOrchestrator`**: Add an optional `usage_meter: UsageMeter | None = None` constructor parameter. In `execute()`, after vision analysis and caption generation, call `await self._usage_meter.emit_all(usages)` if meter is not `None`.

3. **`WebImageService._ensure_orchestrator()`**: Pass `self._usage_meter` when constructing `WorkflowOrchestrator`.

4. **Standalone mode**: `WebImageService.__init__` sets `self._usage_meter = None` when `runtime is None`. `WorkflowOrchestrator` receives `None`. No usage calls are made.

**Accessing the client**: `OrchestratorConfigSource._client` is private. Rather than making it public, expose a public property or method:

```python
# In OrchestratorConfigSource
@property
def orchestrator_client(self) -> OrchestratorClient:
    return self._client
```

Then `WebImageService` can do: `self._config_source.orchestrator_client`.

For `EnvConfigSource`: add a `orchestrator_client` property that returns `None`. Guard in `WebImageService`: `if hasattr(self._config_source, 'orchestrator_client') and self._config_source.orchestrator_client: ...`.

### Acceptance Criteria

- **AC-C1**: `UsageMeter` class exists in `publisher_v2/services/usage_meter.py` with `emit(usage)` and `emit_all(usages)` methods.
- **AC-C2**: `emit()` calls `OrchestratorClient.post_usage()` with `tenant_id`, `metric="ai_tokens"`, `quantity=usage.total_tokens`, `unit="tokens"`, `idempotency_key=usage.response_id`, `occurred_at` (ISO8601 UTC), `source="publisher"`.
- **AC-C3**: If `post_usage()` raises any exception, `emit()` catches it, logs via `log_json` with `event="usage_metering_failed"` (metric, quantity, tenant_id — no secrets), and returns normally. The caller's workflow continues.
- **AC-C4**: `emit_all()` skips entries where `usage is None` or `usage.total_tokens <= 0`.
- **AC-C5**: `WebImageService.analyze_and_caption()` emits usage for both the vision analysis call and the caption generation call(s) after they succeed.
- **AC-C6**: `WorkflowOrchestrator.execute()` emits usage for vision analysis and caption generation when `usage_meter` is provided.
- **AC-C7**: In standalone mode (`EnvConfigSource`, `runtime is None`), `usage_meter` is `None` and no metering calls are made.
- **AC-C8**: `OrchestratorConfigSource` exposes `orchestrator_client` property (public access to its `OrchestratorClient` instance).

---

## Part D — Disambiguate 403 on `resolve_credentials`

**File**: `publisher_v2/src/publisher_v2/config/orchestrator_client.py`

Today (line 133-134):
```python
if resp.status_code == 403:
    raise CredentialResolutionError("Orchestrator authorization failed (403)")
```

The orchestrator's 403 response body distinguishes auth failure from insufficient balance. Update the handler to parse the body:

```python
if resp.status_code == 403:
    try:
        body = resp.json()
    except Exception:
        body = {}
    error_code = body.get("error", "")
    if error_code == "insufficient_balance":
        raise InsufficientBalanceError(
            "Workspace has insufficient credits for this operation"
        )
    raise CredentialResolutionError("Orchestrator authorization failed (403)")
```

**New exception** in `publisher_v2/core/exceptions.py`:

```python
class InsufficientBalanceError(CredentialResolutionError):
    """Workspace cannot afford this platform-billed credential."""
```

Subclassing `CredentialResolutionError` ensures all existing `except CredentialResolutionError` handlers still catch it. Callers that need the distinction can catch `InsufficientBalanceError` first.

### Acceptance Criteria

- **AC-D1**: `InsufficientBalanceError` exists in `publisher_v2/core/exceptions.py`, subclasses `CredentialResolutionError`.
- **AC-D2**: When `resolve_credentials` returns 403 with body `{"error": "insufficient_balance"}`, `InsufficientBalanceError` is raised with message `"Workspace has insufficient credits for this operation"`.
- **AC-D3**: When `resolve_credentials` returns 403 with body `{"error": "forbidden"}` (or any other value, or unparseable body), `CredentialResolutionError` is raised (existing behavior preserved).
- **AC-D4**: Existing `except CredentialResolutionError` handlers still catch `InsufficientBalanceError` (subclass relationship).

---

## Non-Goals

- Per-publish metrics (Telegram posts, emails sent) — no platform-billed cost, not in the price book
- Storage usage (R2 GB-month) — orchestrator controls R2 directly
- Compute/dyno metering — flat infrastructure cost
- A local billing ledger for standalone mode
- Price book management (that's orchestrator-side)
- UI changes — no credits/balance display in the publisher admin (that's orchestrator dashboard)
- Move functionality in the grid (move is a storage internal, not user-facing)
- Changes to any library API endpoint

## Quality Gates

- `ruff check` — zero violations in changed files
- `mypy` — zero errors
- `pytest` — all existing tests pass; new tests for `post_usage`, `UsageMeter`, `AIUsage`, 403 disambiguation
- Coverage ≥ 80% on affected modules

## Implementation Notes

- Test `post_usage()` using `httpx.MockTransport`, following the exact pattern in `tests/config/test_orchestrator_credentials.py` (see `_make_source` helper and `handler` function).
- Mock `OrchestratorClient.post_usage` in `UsageMeter` tests — verify it's called with correct args and that exceptions are swallowed.
- For AI method tests, use a mock OpenAI response with `usage` and `id` attributes. Verify `AIUsage` is correctly populated.
- The `@retry` decorator on AI methods (tenacity) means each retry gets a new `resp.id` — each emits a separate usage event. This is correct: each retry is a real API call that consumed tokens.
- Confirm the `ai_tokens` metric exists in the orchestrator's staging `price_book_entries` before deploying to staging.

## Related

- GitHub Issue: [#57 — Report billable usage to orchestrator](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/57)
- Orchestrator roadmap #14: Usage Ingest & Credential Entitlements (shipped)
- [PUB-022: Orchestrator Schema V2 Integration](archive/PUB-022_orchestrator-schema-v2.md) — established the `OrchestratorClient`
