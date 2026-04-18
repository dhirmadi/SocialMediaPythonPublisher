# PUB-034: Usage Metering — Report Billable AI Consumption to Orchestrator

| Field | Value |
|-------|-------|
| **ID** | PUB-034 |
| **Category** | Foundation |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Proposal |
| **Dependencies** | Orchestrator roadmap #14 (shipped) |
| **GitHub Issue** | #57 |

## Problem

The platform orchestrator has shipped usage ingest and credential entitlements (orchestrator roadmap #14). Metering is **push-based**: the publisher must call `POST /v1/billing/usage` after billable work completes. Today, the publisher's `OrchestratorClient` has no method for this endpoint, and no workflow hooks emit usage events. Consequences:

1. **Wallet debits never occur** for real publisher-driven consumption — the commercial model doesn't function.
2. **Entitlement gates** on `resolve_credentials` (403 when workspace can't afford platform-billed providers) are under-fed in practice.
3. The 403 response from `resolve_credentials` is ambiguous — it could mean "bad token" or "out of credits", but the publisher reports both as `CredentialResolutionError("Orchestrator authorization failed (403)")`.

## Desired Outcome

After any successful OpenAI API call (vision analysis or caption generation), the publisher emits a usage event to the orchestrator with the token count consumed. The orchestrator records the usage, debits the workspace wallet, and the entitlement gate on credential resolution works end-to-end. Standalone (non-orchestrator) mode is unaffected.

## Scope

### Part A — `OrchestratorClient.post_usage()` method

Add a new method to `OrchestratorClient` (`publisher_v2/src/publisher_v2/config/orchestrator_client.py`):

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

- Calls `POST {base_url}/v1/billing/usage` with the service bearer token (same `Authorization: Bearer` as other `/v1` calls — no `X-Tenant` header needed, `tenant_id` is in the body).
- Uses existing `_request_with_retry` for retries on 429/5xx.
- Returns the parsed JSON response on 200.
- Raises `UsageMeteringError` (new exception) on 422 (invalid body / unknown metric).
- Raises `CredentialResolutionError` on 403 (reuse — the service token is bad).
- Raises `OrchestratorUnavailableError` on network/5xx exhaustion.
- **Duplicate idempotency keys are treated as success** (orchestrator returns 200 with no second debit).

### Part B — Emit `ai_tokens` after OpenAI calls

Instrument the AI service layer to emit usage after each successful OpenAI API call. The OpenAI Python SDK response object exposes `resp.usage.total_tokens` (int), `resp.usage.prompt_tokens`, and `resp.usage.completion_tokens`.

**Call sites** (all in `publisher_v2/src/publisher_v2/services/ai.py`):

| Method | Model used | When to emit |
|--------|-----------|-------------|
| `VisionAnalyzerOpenAI.analyze()` | `vision_model` (gpt-4o) | After `resp` is obtained (line ~147), before returning `ImageAnalysis` |
| `CaptionGeneratorOpenAI.generate()` | `caption_model` | After `resp` at line ~287 |
| `CaptionGeneratorOpenAI.generate_with_sd()` | `sd_caption_model` | After `resp` at line ~328 |
| `CaptionGeneratorOpenAI.generate_multi()` | `caption_model` | After `resp` at line ~375 |
| `CaptionGeneratorOpenAI.generate_multi_with_sd()` | `sd_caption_model` | After `resp` at line ~430 |

**Metric**: `ai_tokens` for all call sites. One metric regardless of model — the orchestrator's price book determines cost per unit.

**Quantity**: `resp.usage.total_tokens` (prompt + completion).

**Idempotency key**: `resp.id` (the OpenAI response ID, e.g. `chatcmpl-abc123` — globally unique per API call, safe across retries of the same logical OpenAI call via tenacity `@retry`).

**`occurred_at`**: `datetime.now(timezone.utc).isoformat()` captured at the moment `resp` is received.

**`tenant_id`**: The AI classes don't currently know their tenant. The metering call site should be in the caller (workflow / web service) rather than inside the AI class itself. Two options:
- **Option 1 (preferred)**: AI methods return `resp.usage` alongside their normal return value (e.g. via a wrapper dataclass or by adding usage fields to return types). The caller (`WorkflowOrchestrator.execute()`, `WebImageService.analyze_image()`) then calls `post_usage()` with the tenant context it already has.
- **Option 2**: Pass a metering callback into the AI classes at construction time. Less preferred — adds coupling.

**Failure handling**: Usage emission is **fire-and-forget with structured logging**. If `post_usage()` raises, the publisher logs the failure (status code, metric, quantity — no secrets) and continues. A failed metering call must **never** block or fail the image workflow. The AI operation already succeeded; the user should get their result.

### Part C — Disambiguate 403 on `resolve_credentials`

Today (`orchestrator_client.py` line 133-134):
```python
if resp.status_code == 403:
    raise CredentialResolutionError("Orchestrator authorization failed (403)")
```

After the orchestrator ships entitlement enforcement, 403 from `resolve_credentials` can mean either:
- **Auth failure**: invalid/expired service token
- **Insufficient balance**: workspace can't afford this platform-billed provider

The orchestrator's 403 response body distinguishes these (e.g. `{"error": "insufficient_balance", ...}` vs `{"error": "forbidden", ...}`). Update the handler to:

1. Parse the 403 response body.
2. If `error == "insufficient_balance"` (or equivalent), raise a new `InsufficientBalanceError` (subclass of `CredentialResolutionError`) with a user-friendly message: `"Workspace has insufficient credits for this operation"`.
3. Otherwise, raise the existing `CredentialResolutionError("Orchestrator authorization failed (403)")`.

The web UI / workflow should catch `InsufficientBalanceError` specifically and surface it to the operator — not as a configuration error, but as a billing/credits issue.

### Part D — Standalone mode: no-op

When `config_source` is `EnvConfigSource` (standalone mode, no orchestrator), there is no `OrchestratorClient`. Usage emission simply doesn't happen — no stub, no local ledger, no-op.

The metering call site should guard: `if self._orchestrator_client is not None: await self._orchestrator_client.post_usage(...)`.

## Non-Goals

- Per-publish metrics (Telegram posts, emails sent) — no platform-billed cost, not in the price book
- Storage usage (R2 GB-month) — orchestrator controls R2 directly
- Compute/dyno metering — flat infrastructure cost
- A local billing ledger for standalone mode
- Price book management (that's orchestrator-side)
- UI changes — no credits/balance display in the publisher admin (that's orchestrator dashboard)

## Acceptance Criteria

- **AC1**: `OrchestratorClient.post_usage()` calls `POST /v1/billing/usage` with correct JSON body (`tenant_id`, `source`, `idempotency_key`, `metric`, `quantity`, `unit`, `occurred_at`) and `Authorization: Bearer` header.
- **AC2**: Duplicate `idempotency_key` calls succeed without raising (orchestrator returns 200).
- **AC3**: 422 from orchestrator raises `UsageMeteringError` with the metric name in the message.
- **AC4**: After a successful `VisionAnalyzerOpenAI.analyze()` call, a usage event is emitted with `metric="ai_tokens"`, `quantity=resp.usage.total_tokens`, and `idempotency_key=resp.id`.
- **AC5**: After a successful caption generation call (`generate`, `generate_with_sd`, `generate_multi`, `generate_multi_with_sd`), a usage event is emitted with the same schema.
- **AC6**: If `post_usage()` raises any exception, the AI operation result is still returned to the caller — metering failure never blocks the workflow.
- **AC7**: Metering failures are logged via `log_json` with `event="usage_metering_failed"`, status code, metric, and quantity (no secrets, no bearer tokens).
- **AC8**: In standalone mode (`EnvConfigSource`), no usage calls are made.
- **AC9**: `resolve_credentials` 403 with `"insufficient_balance"` body raises `InsufficientBalanceError` (distinct from generic `CredentialResolutionError`).
- **AC10**: `ruff` / `mypy` / `pytest` gates pass.

## Implementation Notes

- `UsageMeteringError` and `InsufficientBalanceError` go in `publisher_v2/core/exceptions.py`.
- `InsufficientBalanceError` should subclass `CredentialResolutionError` so existing catch clauses still handle it — callers that want the distinction can catch the subclass first.
- The `@retry` decorator on AI methods means the same OpenAI call may be retried by tenacity. Each retry gets a new `resp.id`, so each emits a separate (correct) usage event. If OpenAI itself returns the same response on a retry (unlikely), the idempotency key prevents double-billing.
- Test the client method using `respx` / httpx mock transport, following patterns in `tests/config/test_orchestrator_credentials.py` and `tests/config/test_orchestrator_runtime_config.py`.
- Confirm the `ai_tokens` metric exists in the orchestrator's staging `price_book_entries` before deploying to staging.

## Related

- GitHub Issue: [#57 — Report billable usage to orchestrator](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/57)
- Orchestrator roadmap #14: Usage Ingest & Credential Entitlements (shipped)
- [PUB-022: Orchestrator Schema V2 Integration](archive/PUB-022_orchestrator-schema-v2.md) — established the `OrchestratorClient`
