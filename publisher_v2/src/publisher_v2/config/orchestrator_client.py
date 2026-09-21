"""HTTP client for the Platform Orchestrator service API (runtime, credentials, usage)."""

import asyncio
import os
import random
from dataclasses import dataclass
from typing import Any

import httpx

from publisher_v2.core.exceptions import (
    CredentialResolutionError,
    InsufficientBalanceError,
    OrchestratorUnavailableError,
    TenantNotFoundError,
    UsageMeteringError,
)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True, slots=True)
class RetryConfig:
    """Exponential-backoff parameters shared by every orchestrator request."""

    base_delay_ms: int = 250
    max_delay_ms: int = 5000
    max_attempts: int = 3
    jitter: bool = True


class OrchestratorClient:
    """Async HTTP client for the orchestrator service API (/v1)."""

    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        prefer_post: bool = True,
        timeout_seconds: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Configure the orchestrator endpoint and the service token used to authenticate.

        Args:
            base_url: Orchestrator root URL; a trailing slash is stripped.
            service_token: Bearer token sent on every request. Never logged.
            prefer_post: Try ``POST /v1/runtime/by-host`` first and remember a
                405 so later calls go straight to GET.
            timeout_seconds: Timeout for the client created when ``client`` is
                not supplied.
            client: Pre-built client to use instead (tests inject one); when
                passed, ``timeout_seconds`` is ignored and the caller owns
                closing it.
        """
        self._base_url = base_url.rstrip("/")
        self._token = service_token
        self._prefer_post = prefer_post
        self._post_supported: bool | None = None
        self._retry = RetryConfig()
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def aclose(self) -> None:
        """Close the underlying HTTP client, including one injected by the caller."""
        await self._client.aclose()

    def _headers(self, request_id: str | None = None, tenant: str | None = None) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self._token}"}
        if request_id:
            h["X-Request-Id"] = request_id
        if tenant:
            h["X-Tenant"] = tenant
        return h

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        attempt = 0
        delay_ms = self._retry.base_delay_ms
        last_exc: Exception | None = None

        while attempt < self._retry.max_attempts:
            attempt += 1
            try:
                resp = await self._client.request(method, url, headers=headers, json=json, params=params)
                if resp.status_code in RETRYABLE_STATUS and attempt < self._retry.max_attempts:
                    await self._sleep(delay_ms)
                    delay_ms = min(delay_ms * 2, self._retry.max_delay_ms)
                    continue
                return resp
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt < self._retry.max_attempts:
                    await self._sleep(delay_ms)
                    delay_ms = min(delay_ms * 2, self._retry.max_delay_ms)
                    continue
                break

        raise OrchestratorUnavailableError(f"Orchestrator request failed after {attempt} attempts: {last_exc}")

    async def _sleep(self, delay_ms: int) -> None:
        if self._retry.jitter:
            jitter = random.randint(0, max(1, delay_ms // 4))  # nosec B311 — retry jitter, not a secret
            delay_ms = delay_ms + jitter
        await asyncio.sleep(delay_ms / 1000.0)

    async def get_runtime_by_host(self, host: str, *, request_id: str | None = None) -> dict[str, Any]:
        """Fetch runtime config. Prefer POST when enabled; fall back to GET on 405."""
        url = f"{self._base_url}/v1/runtime/by-host"
        headers = self._headers(request_id=request_id)

        # Prefer POST unless we learned it's unsupported
        if self._prefer_post and self._post_supported is not False:
            resp = await self._request_with_retry("POST", url, headers=headers, json={"host": host})
            if resp.status_code == 405:
                self._post_supported = False
            else:
                self._post_supported = True
                return self._handle_runtime_response(resp)

        resp = await self._request_with_retry("GET", url, headers=headers, params={"host": host})
        return self._handle_runtime_response(resp)

    def _handle_runtime_response(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 200:
            result: dict[str, Any] = resp.json()
            return result
        if resp.status_code == 404:
            raise TenantNotFoundError("Tenant not found")
        if resp.status_code in RETRYABLE_STATUS:
            raise OrchestratorUnavailableError(f"Orchestrator runtime unavailable: {resp.status_code}")
        raise OrchestratorUnavailableError(f"Unexpected orchestrator runtime response: {resp.status_code}")

    async def resolve_credentials(
        self, tenant: str, credentials_ref: str, *, request_id: str | None = None
    ) -> dict[str, Any]:
        """Resolve an opaque credentials ref to secret material for one tenant.

        Args:
            tenant: Tenant id, sent as the ``X-Tenant`` header.
            credentials_ref: Opaque reference issued by the orchestrator.
            request_id: Correlation id forwarded as ``X-Request-Id``.

        Returns:
            The decoded JSON body holding the secret material. Never log it.

        Raises:
            InsufficientBalanceError: 403 with ``error="insufficient_balance"``.
            CredentialResolutionError: 404, any other 403, or an unexpected status.
            OrchestratorUnavailableError: Retryable status after all attempts.
        """
        url = f"{self._base_url}/v1/credentials/resolve"
        headers = self._headers(request_id=request_id, tenant=tenant)
        resp = await self._request_with_retry("POST", url, headers=headers, json={"credentials_ref": credentials_ref})

        if resp.status_code == 200:
            result: dict[str, Any] = resp.json()
            return result
        if resp.status_code == 404:
            raise CredentialResolutionError("Credentials not found or not authorized")
        if resp.status_code == 403:
            try:
                body = resp.json()
            except Exception:
                body = {}
            error_code = body.get("error", "")
            if error_code == "insufficient_balance":
                raise InsufficientBalanceError("Workspace has insufficient credits for this operation")
            raise CredentialResolutionError("Orchestrator authorization failed (403)")
        if resp.status_code in RETRYABLE_STATUS:
            raise OrchestratorUnavailableError(f"Orchestrator credentials unavailable: {resp.status_code}")
        raise CredentialResolutionError(f"Unexpected orchestrator credentials response: {resp.status_code}")

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
        """Report one metered usage event to the orchestrator billing endpoint.

        Args:
            tenant_id: Tenant the usage is billed to.
            metric: Metric name the orchestrator knows (unknown names yield 422).
            quantity: Amount of ``unit`` consumed.
            unit: Unit of ``quantity``, e.g. tokens or posts.
            idempotency_key: Stable key so retries are not double-counted.
            occurred_at: ISO-8601 timestamp of the event.
            source: Reporting component; defaults to ``"publisher"``.
            request_id: Correlation id forwarded as ``X-Request-Id``.

        Returns:
            The decoded JSON acknowledgement body.

        Raises:
            CredentialResolutionError: The service token was rejected (403).
            UsageMeteringError: Unknown tenant (404), rejected body (422), or an
                unexpected status.
            OrchestratorUnavailableError: Retryable status after all attempts.
        """
        url = f"{self._base_url}/v1/billing/usage"
        headers = self._headers(request_id=request_id)
        body = {
            "tenant_id": tenant_id,
            "source": source,
            "idempotency_key": idempotency_key,
            "metric": metric,
            "quantity": quantity,
            "unit": unit,
            "occurred_at": occurred_at,
        }
        resp = await self._request_with_retry("POST", url, headers=headers, json=body)

        if resp.status_code == 200:
            result: dict[str, Any] = resp.json()
            return result
        if resp.status_code == 403:
            raise CredentialResolutionError("Orchestrator authorization failed (403)")
        if resp.status_code == 404:
            raise UsageMeteringError("Tenant not found for usage reporting")
        if resp.status_code == 422:
            raise UsageMeteringError(f"Usage rejected (422): invalid body or unknown metric '{metric}'")
        if resp.status_code in RETRYABLE_STATUS:
            raise OrchestratorUnavailableError(f"Orchestrator usage endpoint unavailable: {resp.status_code}")
        raise UsageMeteringError(f"Unexpected usage response: {resp.status_code}")


def prefer_post_default() -> bool:
    """Read ORCHESTRATOR_PREFER_POST; default True when unset or empty."""
    return (os.environ.get("ORCHESTRATOR_PREFER_POST") or "true").lower() in ("1", "true", "yes", "on")
