"""Shared httpx.AsyncClient pool for service-level HTTP calls.

Why this exists: Vision image downloads were previously opening + tearing down
a fresh TLS connection on every analyze call. With Dropbox CDN that's a
150–400 ms handshake per image. A shared client with keep-alive amortizes the
cost and provides a single place to tune timeouts and pool limits.

The client is lazily created on first use to keep import-time work minimal,
and is disposed via ``aclose_shared_client`` from the FastAPI shutdown hook.
"""

from __future__ import annotations

import asyncio

import httpx

_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()

_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)
_DEFAULT_LIMITS = httpx.Limits(max_keepalive_connections=20, max_connections=40)


async def get_shared_client() -> httpx.AsyncClient:
    """Return the process-wide keep-alive HTTP client, creating it on first use.

    Creation is guarded by an asyncio lock so concurrent first callers share one
    client. The returned client is owned by this module: callers must not close
    it, and must not assume it survives ``aclose_shared_client``.
    """
    global _client
    if _client is not None:
        return _client
    async with _client_lock:
        if _client is None:
            _client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, limits=_DEFAULT_LIMITS)
        return _client


async def aclose_shared_client() -> None:
    """Close the shared client and reset the module slot.

    Idempotent: a no-op when no client has been created. A later
    ``get_shared_client`` call builds a fresh one, so this is safe to call from
    the FastAPI shutdown hook even if requests may still arrive.
    """
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
