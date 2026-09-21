"""Tests for OrchestratorClient.post_usage() — AC-A1 through AC-A7, AC-C8."""

from __future__ import annotations

import json

import httpx
import pytest

from publisher_v2.config.orchestrator_client import OrchestratorClient
from publisher_v2.config.source import OrchestratorConfigSource
from publisher_v2.core.exceptions import CredentialResolutionError, OrchestratorUnavailableError, UsageMeteringError


def _make_client(transport: httpx.MockTransport) -> OrchestratorClient:
    client = httpx.AsyncClient(transport=transport, base_url="https://orch.test")
    orch = OrchestratorClient(base_url="https://orch.test", service_token="svc-token", prefer_post=True, client=client)

    async def _no_sleep(_ms: int) -> None:
        return None

    orch._sleep = _no_sleep  # type: ignore[assignment, method-assign]
    return orch


# --- AC-A1: POST body and Authorization header ---


@pytest.mark.asyncio
async def test_post_usage_sends_correct_request() -> None:
    """AC-A1: post_usage sends POST /v1/billing/usage with JSON body and Bearer header."""
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/billing/usage":
            captured["method"] = request.method
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(500)

    orch = _make_client(httpx.MockTransport(handler))
    await orch.post_usage(
        tenant_id="t-123",
        metric="ai_tokens",
        quantity=500,
        unit="tokens",
        idempotency_key="resp-abc",
        occurred_at="2026-03-16T12:00:00Z",
        source="publisher",
        request_id="req-1",
    )

    assert captured["method"] == "POST"
    assert "Bearer svc-token" in captured["headers"]["authorization"]
    body = captured["body"]
    assert body["tenant_id"] == "t-123"
    assert body["metric"] == "ai_tokens"
    assert body["quantity"] == 500
    assert body["unit"] == "tokens"
    assert body["idempotency_key"] == "resp-abc"
    assert body["occurred_at"] == "2026-03-16T12:00:00Z"
    assert body["source"] == "publisher"


# --- AC-A2: 200 returns parsed JSON ---


@pytest.mark.asyncio
async def test_post_usage_200_returns_dict() -> None:
    """AC-A2: 200 response returns parsed JSON dict without raising."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok", "id": "usage-1"})

    orch = _make_client(httpx.MockTransport(handler))
    result = await orch.post_usage(
        tenant_id="t-123",
        metric="ai_tokens",
        quantity=100,
        unit="tokens",
        idempotency_key="key-1",
        occurred_at="2026-03-16T12:00:00Z",
    )
    assert result == {"status": "ok", "id": "usage-1"}


# --- AC-A3: Duplicate idempotency key (200) is success ---


@pytest.mark.asyncio
async def test_post_usage_duplicate_idempotency_key_success() -> None:
    """AC-A3: Duplicate idempotency_key (200 response) is treated as success."""
    call_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"status": "ok", "duplicate": True})

    orch = _make_client(httpx.MockTransport(handler))
    # First call
    r1 = await orch.post_usage(
        tenant_id="t-1", metric="ai_tokens", quantity=10, unit="tokens", idempotency_key="dup-key", occurred_at="now"
    )
    # Second call with same key
    r2 = await orch.post_usage(
        tenant_id="t-1", metric="ai_tokens", quantity=10, unit="tokens", idempotency_key="dup-key", occurred_at="now"
    )
    assert r1["status"] == "ok"
    assert r2["status"] == "ok"
    assert call_count == 2


# --- AC-A4: 422 raises UsageMeteringError with metric ---


@pytest.mark.asyncio
async def test_post_usage_422_raises_usage_metering_error() -> None:
    """AC-A4: 422 response raises UsageMeteringError with the metric name in the message."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": "invalid_metric"})

    orch = _make_client(httpx.MockTransport(handler))
    with pytest.raises(UsageMeteringError, match="ai_tokens"):
        await orch.post_usage(
            tenant_id="t-1",
            metric="ai_tokens",
            quantity=10,
            unit="tokens",
            idempotency_key="k",
            occurred_at="now",
        )


# --- AC-A5: 403 raises CredentialResolutionError ---


@pytest.mark.asyncio
async def test_post_usage_403_raises_credential_resolution_error() -> None:
    """AC-A5: 403 response raises CredentialResolutionError."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "forbidden"})

    orch = _make_client(httpx.MockTransport(handler))
    with pytest.raises(CredentialResolutionError):
        await orch.post_usage(
            tenant_id="t-1",
            metric="ai_tokens",
            quantity=10,
            unit="tokens",
            idempotency_key="k",
            occurred_at="now",
        )


# --- AC-A6: 404 raises UsageMeteringError ---


@pytest.mark.asyncio
async def test_post_usage_404_raises_usage_metering_error() -> None:
    """AC-A6: 404 response raises UsageMeteringError."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not_found"})

    orch = _make_client(httpx.MockTransport(handler))
    with pytest.raises(UsageMeteringError, match="Tenant not found"):
        await orch.post_usage(
            tenant_id="t-1",
            metric="ai_tokens",
            quantity=10,
            unit="tokens",
            idempotency_key="k",
            occurred_at="now",
        )


# --- AC-A7: 5xx after retry exhaustion raises OrchestratorUnavailableError ---


@pytest.mark.asyncio
async def test_post_usage_5xx_raises_orchestrator_unavailable() -> None:
    """AC-A7: 5xx after retry exhaustion raises OrchestratorUnavailableError."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    orch = _make_client(httpx.MockTransport(handler))
    with pytest.raises(OrchestratorUnavailableError):
        await orch.post_usage(
            tenant_id="t-1",
            metric="ai_tokens",
            quantity=10,
            unit="tokens",
            idempotency_key="k",
            occurred_at="now",
        )


# --- AC-C8: OrchestratorConfigSource exposes orchestrator_client property ---


@pytest.mark.asyncio
async def test_orchestrator_config_source_exposes_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-C8: OrchestratorConfigSource.orchestrator_client returns the OrchestratorClient instance."""
    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orch.test")
    monkeypatch.setenv("ORCHESTRATOR_SERVICE_TOKEN", "svc-token")
    monkeypatch.setenv("ORCHESTRATOR_BASE_DOMAIN", "shibari.photo")
    monkeypatch.setenv("DROPBOX_APP_KEY", "app_key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "app_secret")
    monkeypatch.setenv("CREDENTIAL_CACHE_ENABLED", "true")
    monkeypatch.setenv("CREDENTIAL_CACHE_TTL_SECONDS", "600")

    src = OrchestratorConfigSource()
    client = src.orchestrator_client
    assert isinstance(client, OrchestratorClient)


# --- PUB-061 AC1: per-call single-attempt retry override for drain posts ---


def _make_counting_client(transport: httpx.MockTransport) -> tuple[OrchestratorClient, list[int]]:
    """Build a client whose backoff sleeps are recorded instead of awaited."""
    client = httpx.AsyncClient(transport=transport, base_url="https://orch.test")
    orch = OrchestratorClient(base_url="https://orch.test", service_token="svc-token", prefer_post=True, client=client)
    sleeps: list[int] = []

    async def _record_sleep(ms: int) -> None:
        sleeps.append(ms)

    orch._sleep = _record_sleep  # type: ignore[assignment, method-assign]
    return orch, sleeps


@pytest.mark.asyncio
async def test_post_usage_single_attempt_calls_transport_once_without_backoff() -> None:
    """PUB-061 AC1: with the single-attempt retry override, a retryable status is not retried."""
    from publisher_v2.config.orchestrator_client import RetryConfig

    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    orch, sleeps = _make_counting_client(httpx.MockTransport(handler))

    with pytest.raises(OrchestratorUnavailableError):
        await orch.post_usage(
            tenant_id="t-1",
            metric="storage_ops_requests",
            quantity=10,
            unit="requests",
            idempotency_key="k",
            occurred_at="2026-09-21T00:00:00+00:00",
            retry=RetryConfig(max_attempts=1),
        )

    assert calls == 1, f"single-attempt override must hit the transport once, got {calls}"
    assert sleeps == [], f"single-attempt override must not back off, slept {sleeps}"


@pytest.mark.asyncio
async def test_post_usage_without_override_keeps_three_attempt_behaviour() -> None:
    """PUB-061 AC1 (regression guard): the default path still retries three times with backoff."""
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    orch, sleeps = _make_counting_client(httpx.MockTransport(handler))

    with pytest.raises(OrchestratorUnavailableError):
        await orch.post_usage(
            tenant_id="t-1",
            metric="storage_ops_requests",
            quantity=10,
            unit="requests",
            idempotency_key="k",
            occurred_at="2026-09-21T00:00:00+00:00",
        )

    assert calls == 3
    assert len(sleeps) == 2


# --- PUB-061 review nit: _sleep must honour the per-call retry policy's jitter flag ---


def _make_real_sleep_client(
    transport: httpx.MockTransport, monkeypatch: pytest.MonkeyPatch
) -> tuple[OrchestratorClient, list[float]]:
    """Client whose real ``_sleep`` body runs, with the awaited ``asyncio.sleep`` recorded.

    Deliberately does NOT stub ``_sleep`` — stubbing it is what hides jitter bugs.
    ``asyncio.sleep`` is replaced (monkeypatch restores it) so the recorded values
    are the exact delays ``_sleep`` computed, and nothing really sleeps.
    """
    from publisher_v2.config import orchestrator_client as oc_module

    client = httpx.AsyncClient(transport=transport, base_url="https://orch.test")
    orch = OrchestratorClient(base_url="https://orch.test", service_token="svc-token", prefer_post=True, client=client)
    slept: list[float] = []

    async def _fake_asyncio_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(oc_module.asyncio, "sleep", _fake_asyncio_sleep)
    # Deterministic jitter: always the maximum the implementation allows (delay_ms // 4),
    # so "jitter applied" vs "no jitter" is an exact, non-flaky comparison.
    monkeypatch.setattr(oc_module.random, "randint", lambda _lo, hi: hi)
    return orch, slept


def _retryable_503_handler(counter: list[int]):
    async def handler(request: httpx.Request) -> httpx.Response:
        counter.append(1)
        return httpx.Response(503)

    return handler


@pytest.mark.asyncio
async def test_post_usage_per_call_jitter_disabled_uses_deterministic_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-call RetryConfig(jitter=False) must produce exact base, base*2 delays (no jitter)."""
    from publisher_v2.config.orchestrator_client import RetryConfig

    policy = RetryConfig(jitter=False, max_attempts=3)
    calls: list[int] = []
    orch, slept = _make_real_sleep_client(httpx.MockTransport(_retryable_503_handler(calls)), monkeypatch)

    with pytest.raises(OrchestratorUnavailableError):
        await orch.post_usage(
            tenant_id="t-1",
            metric="storage_ops_requests",
            quantity=10,
            unit="requests",
            idempotency_key="k",
            occurred_at="2026-09-21T00:00:00+00:00",
            retry=policy,
        )

    assert len(calls) == 3
    expected = [policy.base_delay_ms / 1000.0, policy.base_delay_ms * 2 / 1000.0]
    assert slept == expected, f"per-call jitter=False must not jitter: expected {expected}, slept {slept}"


@pytest.mark.asyncio
async def test_post_usage_default_policy_still_applies_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression guard: with no per-call override the default policy (jitter=True) still jitters."""
    calls: list[int] = []
    orch, slept = _make_real_sleep_client(httpx.MockTransport(_retryable_503_handler(calls)), monkeypatch)

    with pytest.raises(OrchestratorUnavailableError):
        await orch.post_usage(
            tenant_id="t-1",
            metric="storage_ops_requests",
            quantity=10,
            unit="requests",
            idempotency_key="k",
            occurred_at="2026-09-21T00:00:00+00:00",
        )

    assert len(calls) == 3
    # randint is stubbed to its upper bound (delay_ms // 4): 250 -> 250+62, 500 -> 500+125.
    assert slept == [0.312, 0.625], f"default policy must jitter, slept {slept}"
    assert slept != [0.25, 0.5], "default policy must not fall back to un-jittered backoff"
