# PUB-034 Implementation Handoff — Usage Metering

**Hardened**: 2026-03-16
**Status**: Ready for implementation
**Spec**: `docs_v2/roadmap/PUB-034_usage-metering.md`

---

## Implementation Order

1. **Part A**: `OrchestratorClient.post_usage()` + `UsageMeteringError` exception
2. **Part D**: 403 disambiguation on `resolve_credentials` + `InsufficientBalanceError` exception
3. **Part B**: `AIUsage` dataclass + return usage from AI methods
4. **Part C**: `UsageMeter` class + integration into `WebImageService` and `WorkflowOrchestrator`

Parts A and D are independent backend additions. Part B changes AI method signatures (many callers to update). Part C wires everything together.

---

## Test-First Targets

| AC | Test file | Key test cases |
|----|-----------|----------------|
| AC-A1..A3 | `publisher_v2/tests/config/test_orchestrator_usage.py` (new) | Mock transport: 200 → success; 200 on duplicate → success |
| AC-A4 | same | Mock transport: 422 → `UsageMeteringError` with metric in message |
| AC-A5 | same | Mock transport: 403 → `CredentialResolutionError` |
| AC-A6 | same | Mock transport: 404 → `UsageMeteringError` |
| AC-A7 | same | Mock transport: 500 × 3 → `OrchestratorUnavailableError` |
| AC-D1..D3 | `publisher_v2/tests/config/test_orchestrator_credentials.py` (extend) | 403 + `{"error": "insufficient_balance"}` → `InsufficientBalanceError`; 403 + `{"error": "forbidden"}` → `CredentialResolutionError`; 403 + unparseable body → `CredentialResolutionError` |
| AC-D4 | same | `isinstance(InsufficientBalanceError(...), CredentialResolutionError)` is `True` |
| AC-B1 | `publisher_v2/tests/test_ai_usage.py` (new) | `AIUsage` dataclass instantiation |
| AC-B2..B4 | same | Mock OpenAI client returning resp with `usage` attrs → verify AIUsage; resp with `usage=None` → AIUsage is None |
| AC-B5 | same | `AIService.create_caption_pair_from_analysis` returns list of AIUsage |
| AC-C1..C4 | `publisher_v2/tests/test_usage_meter.py` (new) | `emit()` calls `post_usage` with correct args; exception swallowed + logged; `emit_all` skips None/zero entries |
| AC-C5..C6 | `publisher_v2/tests/test_usage_meter.py` or integration | `analyze_and_caption` / `execute` call `emit_all` with collected usages |
| AC-C7 | same | Standalone mode → `usage_meter is None` → no calls |
| AC-C8 | `publisher_v2/tests/config/test_orchestrator_usage.py` | `OrchestratorConfigSource.orchestrator_client` returns the client |

---

## Mock Boundaries

| External service | Mock strategy | Existing pattern |
|-----------------|---------------|------------------|
| Orchestrator HTTP | `httpx.MockTransport` | `tests/config/test_orchestrator_credentials.py::_make_source` |
| OpenAI API | Mock `AsyncOpenAI` client | `tests/` — create a mock response object with `.usage.total_tokens`, `.usage.prompt_tokens`, `.usage.completion_tokens`, `.id` attrs |
| `OrchestratorClient.post_usage` | `unittest.mock.AsyncMock` | For `UsageMeter` tests — verify call args, simulate exceptions |
| `log_json` | `unittest.mock.patch` | Verify structured log on metering failure |

---

## Files to Modify

| Area | File | What changes |
|------|------|-------------|
| Exceptions | `publisher_v2/src/publisher_v2/core/exceptions.py` | Add `UsageMeteringError`, `InsufficientBalanceError` |
| Client | `publisher_v2/src/publisher_v2/config/orchestrator_client.py` | Add `post_usage()` method; update `resolve_credentials` 403 handler |
| Config source | `publisher_v2/src/publisher_v2/config/source.py` | Add `orchestrator_client` property to `OrchestratorConfigSource`; add same (returning `None`) to `EnvConfigSource` |
| Models | `publisher_v2/src/publisher_v2/core/models.py` | Add `AIUsage` dataclass |
| AI service | `publisher_v2/src/publisher_v2/services/ai.py` | Change return types of 5 low-level methods + AIService public methods to include `AIUsage` |
| Workflow | `publisher_v2/src/publisher_v2/core/workflow.py` | Accept `usage_meter` param; collect usage from AI calls; call `emit_all` |
| Web service | `publisher_v2/src/publisher_v2/web/service.py` | Construct `UsageMeter` in orchestrated mode; pass to workflow; emit usage in `analyze_and_caption` |

## Files to Create

| File | Purpose |
|------|---------|
| `publisher_v2/src/publisher_v2/services/usage_meter.py` | `UsageMeter` class |
| `publisher_v2/tests/config/test_orchestrator_usage.py` | Tests for `post_usage()` |
| `publisher_v2/tests/test_ai_usage.py` | Tests for `AIUsage` + AI method usage extraction |
| `publisher_v2/tests/test_usage_meter.py` | Tests for `UsageMeter.emit()` / `emit_all()` |

---

## Non-Negotiables

- **Metering never blocks the workflow**: If `post_usage()` fails, the image result is still returned. Fire-and-forget with logging.
- **No secrets in logs**: Never log bearer tokens or full request bodies. Log metric, quantity, tenant_id only.
- **Preview mode**: Usage emission still occurs in preview mode if AI calls happen — preview prevents publishing, not analysis. (Preview mode currently skips the entire workflow, so in practice AI is not invoked. But if the web UI's `analyze_and_caption` is called, it should emit.)
- **Standalone mode**: No `OrchestratorClient` exists, `usage_meter` is `None`, zero metering calls.
- **Coverage**: ≥80% on affected modules.

---

## Key Design Decisions

1. **`AIUsage` dataclass, not raw dict** — typed, testable, no stringly-typed contracts.
2. **Tuple return from AI methods** — `(result, AIUsage | None)` keeps the change minimal. Alternative (wrapper class) was considered but adds more boilerplate for the same information.
3. **`UsageMeter` as a collaborator** — avoids scattering orchestrator client references into workflow/web service. Single responsibility: call `post_usage` with fire-and-forget semantics.
4. **`InsufficientBalanceError` subclasses `CredentialResolutionError`** — existing catch blocks still work; callers that care can catch the subclass first.
5. **One metric (`ai_tokens`)** — the publisher doesn't distinguish vision vs caption pricing. The orchestrator's price book handles differentiation if needed.
6. **`resp.id` as idempotency key** — globally unique per OpenAI API call, naturally deduplicates retries.

---

## Potential Gotchas

1. **AI method signature change has wide blast radius** — `analyze()` returns `(ImageAnalysis, AIUsage | None)` instead of `ImageAnalysis`. Every caller must be updated. Search for `analyzer.analyze(` and `generator.generate(` across the codebase.
2. **`_extract_usage` with test doubles** — the mock OpenAI client in tests may not have `resp.usage`. The `_extract_usage` helper must handle `AttributeError` / `None` gracefully.
3. **`OrchestratorConfigSource._client` is private** — exposing it as `orchestrator_client` property is a small but deliberate API surface change. `EnvConfigSource` must also get the property (returning `None`) to avoid `AttributeError` in the guard.
4. **Confirm `ai_tokens` in staging price book** — if the metric doesn't exist, `post_usage` will get 422 in staging. This is an ops prerequisite, not a code issue.

---

## Claude Code Command

```
/implement docs_v2/roadmap/PUB-034_usage-metering.md
```
