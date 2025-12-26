from __future__ import annotations

import pytest

from publisher_v2.config.runtime_cache import RuntimeConfigCache


def test_cache_hit_miss_and_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    import publisher_v2.config.runtime_cache as rc_mod

    now = 1000.0

    def _time() -> float:
        return now

    monkeypatch.setattr(rc_mod.time, "time", _time)

    cache: RuntimeConfigCache[str, str] = RuntimeConfigCache(max_size=2)

    v, fresh = cache.get("k1")
    assert v is None and fresh is False
    assert cache.stats.miss_total == 1

    cache.set("k1", "v1", ttl_seconds=10)
    v, fresh = cache.get("k1")
    assert v == "v1" and fresh is True
    assert cache.stats.hit_total == 1

    # Expire but keep entry for stale serving
    now = 2000.0
    v, fresh = cache.get("k1")
    assert v == "v1" and fresh is False
    cache.mark_stale_served()
    assert cache.stats.stale_serve_total == 1


def test_cache_lru_eviction(monkeypatch: pytest.MonkeyPatch) -> None:
    import publisher_v2.config.runtime_cache as rc_mod

    now = 1000.0
    monkeypatch.setattr(rc_mod.time, "time", lambda: now)

    cache: RuntimeConfigCache[str, str] = RuntimeConfigCache(max_size=2)
    cache.set("a", "A", ttl_seconds=100)
    cache.set("b", "B", ttl_seconds=100)

    # Touch 'a' so 'b' becomes LRU
    v, fresh = cache.get("a")
    assert v == "A" and fresh is True

    cache.set("c", "C", ttl_seconds=100)

    # 'b' should be evicted
    v, fresh = cache.get("b")
    assert v is None and fresh is False

