from __future__ import annotations

import asyncio
import pytest

from publisher_v2.config.credential_cache import CredentialCache, SingleFlight


def test_cache_key_ttl_lru(monkeypatch: pytest.MonkeyPatch) -> None:
    import publisher_v2.config.credential_cache as cc_mod

    now = 1000.0
    monkeypatch.setattr(cc_mod.time, "time", lambda: now)

    cache: CredentialCache[str, str] = CredentialCache(max_size=2)

    assert cache.get("k1") is None
    assert cache.stats.miss_total == 1

    cache.set("k1", "v1", ttl_seconds=10)
    assert cache.get("k1") == "v1"
    assert cache.stats.hit_total == 1

    # Expire
    now = 2000.0
    assert cache.get("k1") is None

    # LRU eviction
    now = 1000.0
    cache.set("a", "A", ttl_seconds=100)
    cache.set("b", "B", ttl_seconds=100)
    # Touch 'a' so 'b' is LRU
    assert cache.get("a") == "A"
    cache.set("c", "C", ttl_seconds=100)
    assert cache.get("b") is None


@pytest.mark.asyncio
async def test_single_flight_coalesces_concurrent_requests() -> None:
    sf = SingleFlight()
    calls = 0

    async def fn() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)  # allow scheduling
        return 42

    res = await asyncio.gather(sf.do("k", fn), sf.do("k", fn), sf.do("k", fn))
    assert res == [42, 42, 42]
    assert calls == 1


@pytest.mark.asyncio
async def test_single_flight_does_not_cache_failures() -> None:
    sf = SingleFlight()
    calls = 0

    async def bad() -> int:
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await sf.do("k", bad)
    with pytest.raises(RuntimeError):
        await sf.do("k", bad)
    assert calls == 2


def test_metrics_hit_miss() -> None:
    cache: CredentialCache[str, str] = CredentialCache(max_size=10)
    assert cache.get("x") is None
    cache.set("x", "y", ttl_seconds=100)
    assert cache.get("x") == "y"
    assert cache.stats.miss_total >= 1
    assert cache.stats.hit_total >= 1

