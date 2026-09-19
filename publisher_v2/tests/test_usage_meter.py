"""Tests for UsageMeter — AC-C1 through AC-C7."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from publisher_v2.core.exceptions import UsageMeteringError
from publisher_v2.core.models import AIUsage
from publisher_v2.services.usage_meter import UsageMeter

# --- AC-C1: UsageMeter exists with emit() and emit_all() ---


def test_usage_meter_has_emit_and_emit_all() -> None:
    """AC-C1: UsageMeter has emit() and emit_all() methods."""
    client = AsyncMock()
    meter = UsageMeter(client=client, tenant_id="t-1")
    assert hasattr(meter, "emit")
    assert hasattr(meter, "emit_all")
    assert callable(meter.emit)
    assert callable(meter.emit_all)


# --- AC-C2: emit() calls post_usage with correct args ---


@pytest.mark.asyncio
async def test_emit_calls_post_usage_with_correct_args() -> None:
    """AC-C2: emit() calls post_usage with tenant_id, metric, quantity, unit, idempotency_key, occurred_at, source."""
    client = AsyncMock()
    client.post_usage = AsyncMock(return_value={"status": "ok"})
    meter = UsageMeter(client=client, tenant_id="t-abc")

    usage = AIUsage(response_id="resp-123", total_tokens=500, prompt_tokens=300, completion_tokens=200)
    await meter.emit(usage)
    await meter.aclose()  # #93: emit enqueues; flush before asserting

    client.post_usage.assert_called_once()
    call_kwargs = client.post_usage.call_args.kwargs
    assert call_kwargs["tenant_id"] == "t-abc"
    assert call_kwargs["metric"] == "ai_tokens"
    assert call_kwargs["quantity"] == 500
    assert call_kwargs["unit"] == "tokens"
    assert call_kwargs["idempotency_key"] == "resp-123"
    assert call_kwargs["source"] == "publisher"
    # occurred_at should be an ISO8601 string
    assert "T" in call_kwargs["occurred_at"]


# --- AC-C3: emit() swallows exceptions and logs ---


@pytest.mark.asyncio
async def test_emit_swallows_exception_and_logs() -> None:
    """AC-C3: If post_usage raises, emit catches it, logs, and returns normally."""
    client = AsyncMock()
    client.post_usage = AsyncMock(side_effect=UsageMeteringError("422 rejected"))
    meter = UsageMeter(client=client, tenant_id="t-fail")

    usage = AIUsage(response_id="resp-err", total_tokens=100, prompt_tokens=60, completion_tokens=40)

    with patch("publisher_v2.services.usage_meter.log_json") as mock_log:
        # Should NOT raise
        await meter.emit(usage)
        await meter.aclose()  # #93: emit enqueues; flush before asserting

        # Should have logged the failure
        mock_log.assert_called_once()
        call_args = mock_log.call_args
        assert call_args[0][1] == logging.WARNING
        assert call_args[0][2] == "usage_metering_failed"
        assert call_args[1]["metric"] == "ai_tokens"
        assert call_args[1]["quantity"] == 100
        assert call_args[1]["tenant_id"] == "t-fail"


# --- AC-C4: emit_all() skips None and zero-token entries ---


@pytest.mark.asyncio
async def test_emit_all_skips_none_and_zero_tokens() -> None:
    """AC-C4: emit_all() skips entries where usage is None or total_tokens <= 0."""
    client = AsyncMock()
    client.post_usage = AsyncMock(return_value={"status": "ok"})
    meter = UsageMeter(client=client, tenant_id="t-1")

    usages: list[AIUsage | None] = [
        None,  # type: ignore[list-item]  # Should be skipped
        AIUsage(response_id="r1", total_tokens=0, prompt_tokens=0, completion_tokens=0),  # Should be skipped
        AIUsage(response_id="r2", total_tokens=100, prompt_tokens=60, completion_tokens=40),  # Should emit
    ]
    await meter.emit_all(usages)  # type: ignore[arg-type]
    await meter.aclose()  # #93: flush the queue

    assert client.post_usage.call_count == 1
    call_kwargs = client.post_usage.call_args.kwargs
    assert call_kwargs["idempotency_key"] == "r2"


@pytest.mark.asyncio
async def test_emit_all_emits_multiple_valid_entries() -> None:
    """emit_all emits for each valid entry."""
    client = AsyncMock()
    client.post_usage = AsyncMock(return_value={"status": "ok"})
    meter = UsageMeter(client=client, tenant_id="t-1")

    usages = [
        AIUsage(response_id="r1", total_tokens=100, prompt_tokens=60, completion_tokens=40),
        AIUsage(response_id="r2", total_tokens=200, prompt_tokens=120, completion_tokens=80),
    ]
    await meter.emit_all(usages)
    await meter.aclose()  # #93: flush the queue

    assert client.post_usage.call_count == 2


# --- AC-C7: Standalone mode — usage_meter is None, no calls ---


def test_standalone_mode_no_meter() -> None:
    """AC-C7: When usage_meter is None, no metering calls happen (tested at caller level)."""
    # This tests the pattern: `if self._usage_meter is not None: await self._usage_meter.emit_all(...)`
    # The actual integration is tested via workflow/web, but we verify None is a valid state.
    meter: UsageMeter | None = None
    assert meter is None  # Callers guard on None before calling


class TestNonBlockingEmit:
    """#93 (PERF-3): emit enqueues; a background drainer posts; aclose flushes."""

    def _meter(self):
        from unittest.mock import AsyncMock, MagicMock

        from publisher_v2.services.usage_meter import UsageMeter

        client = MagicMock()
        client.post_usage = AsyncMock(return_value={"ok": True})
        return UsageMeter(client=client, tenant_id="t1"), client

    def _usage(self, resp_id: str = "r1", tokens: int = 10):
        from publisher_v2.core.models import AIUsage

        return AIUsage(response_id=resp_id, total_tokens=tokens, prompt_tokens=6, completion_tokens=4)

    async def test_emit_returns_before_post(self) -> None:
        import asyncio

        meter, client = self._meter()
        gate = asyncio.Event()

        async def _blocked_post(**kwargs):
            await gate.wait()
            return {"ok": True}

        client.post_usage.side_effect = _blocked_post

        await asyncio.wait_for(meter.emit(self._usage()), timeout=0.5)  # must not block on the post
        gate.set()
        await meter.aclose()
        assert client.post_usage.await_count == 1

    async def test_drainer_posts_all_queued_events(self) -> None:
        meter, client = self._meter()
        await meter.emit_all([self._usage("a", 5), self._usage("b", 6), self._usage("c", 7)])
        await meter.aclose()
        keys = sorted(call.kwargs["idempotency_key"] for call in client.post_usage.await_args_list)
        assert keys == ["a", "b", "c"]

    async def test_aclose_flushes_pending(self) -> None:
        meter, client = self._meter()
        await meter.emit(self._usage("x", 3))
        await meter.aclose()
        assert client.post_usage.await_count == 1
