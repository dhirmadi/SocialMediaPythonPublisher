"""Centralized runtime tunables read from the environment (#97 stage 2).

Every ad-hoc ``os.environ`` tunable that used to live in services, core, and
web modules is parsed here. Call sites invoke :func:`load_runtime_settings`
at the moment they previously read the env var, so per-process overrides via
the environment (and tests using ``monkeypatch.setenv``) keep working —
values are parsed fresh on each call, never cached.

Parsing is deliberately lenient, matching the old call sites: an invalid
value falls back to the default instead of raising, and the historical
clamps (publish timeout >= 5s, AI stage timeout >= 0.1s) are preserved.
"""

from __future__ import annotations

import os

from pydantic import BaseModel


def _float_env(name: str, default: float | None) -> float | None:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_env(name: str, default: int | None) -> int | None:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class RuntimeSettings(BaseModel):
    """Runtime tunables. Optional fields fall back to static config at the call site."""

    ai_rate_per_minute: int | None = None
    publish_timeout_seconds: float = 120.0
    ai_stage_timeout_seconds: float = 150.0
    web_image_cache_ttl_seconds: float | None = None
    caption_history_retention_days: int = 90
    tenant_service_cache_max_size: int = 1000
    tenant_service_ttl_seconds: int = 600
    library_max_upload_mb: int = 20
    library_scan_budget: int = 5000
    publish_timeout_overrides: dict[str, float] = {}

    def publish_timeout_for(self, platform: str) -> float:
        """Per-platform publish timeout, e.g. ``PUBLISH_TIMEOUT_TELEGRAM_SECONDS=30``."""
        return self.publish_timeout_overrides.get(platform.lower(), self.publish_timeout_seconds)


def load_runtime_settings() -> RuntimeSettings:
    """Parse all runtime tunables from the environment (fresh read, no cache)."""
    defaults = RuntimeSettings()

    rate = _int_env("AI_RATE_PER_MINUTE", None)
    if rate is not None and rate <= 0:
        rate = None

    publish_timeout = _float_env("PUBLISH_TIMEOUT_SECONDS", defaults.publish_timeout_seconds)
    publish_timeout = max(5.0, publish_timeout if publish_timeout is not None else defaults.publish_timeout_seconds)

    ai_stage = _float_env("AI_STAGE_TIMEOUT_SECONDS", defaults.ai_stage_timeout_seconds)
    ai_stage = max(0.1, ai_stage if ai_stage is not None else defaults.ai_stage_timeout_seconds)

    ttl = _float_env("WEB_IMAGE_CACHE_TTL_SECONDS", None)
    if ttl is not None and ttl <= 0:
        ttl = None

    overrides: dict[str, float] = {}
    prefix, suffix = "PUBLISH_TIMEOUT_", "_SECONDS"
    for key in os.environ:
        if key.startswith(prefix) and key.endswith(suffix) and key != "PUBLISH_TIMEOUT_SECONDS":
            platform = key[len(prefix) : -len(suffix)].lower()
            if not platform:
                continue
            value = _float_env(key, None)
            if value is not None:
                overrides[platform] = max(5.0, value)

    return RuntimeSettings(
        ai_rate_per_minute=rate,
        publish_timeout_seconds=publish_timeout,
        ai_stage_timeout_seconds=ai_stage,
        web_image_cache_ttl_seconds=ttl,
        caption_history_retention_days=_int_env(
            "PV2_CAPTION_HISTORY_RETENTION_DAYS", defaults.caption_history_retention_days
        )
        or defaults.caption_history_retention_days,
        tenant_service_cache_max_size=_int_env("TENANT_SERVICE_CACHE_MAX_SIZE", None)
        or defaults.tenant_service_cache_max_size,
        tenant_service_ttl_seconds=_int_env("TENANT_SERVICE_TTL_SECONDS", None) or defaults.tenant_service_ttl_seconds,
        library_max_upload_mb=_int_env("LIBRARY_MAX_UPLOAD_MB", None) or defaults.library_max_upload_mb,
        library_scan_budget=_int_env("LIBRARY_SCAN_BUDGET", None) or defaults.library_scan_budget,
        publish_timeout_overrides=overrides,
    )
