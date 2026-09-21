"""Centralized runtime tunables read from the environment (#97 stage 2).

Every ad-hoc ``os.environ`` tunable that used to live in services, core, and
web modules is parsed here.

:func:`load_runtime_settings` itself always parses the environment fresh — it
holds no cache, so a CLI run or a test using ``monkeypatch.setenv`` sees the
current environment. What changed in #143 is *who calls it and how often*: the
web process parses once in the FastAPI lifespan and stores the result on
``app.state.runtime_settings``, and components take a :class:`RuntimeSettings`
at construction time and keep it. A request therefore reads a snapshot taken at
process start rather than re-parsing the environment per call, and changing an
env var in a running web process no longer takes effect mid-process. Tests that
need a different value either set the env before building the component or pass
``settings=`` explicitly.

Parsing is deliberately lenient, matching the old call sites: an
*unparseable* value falls back to the default instead of raising, and the
historical clamps (publish timeout >= 5s, AI stage timeout >= 0.1s) are
preserved. The one exception is the PUB-047 timeout budgets, where a parseable
but non-positive value raises :class:`ConfigurationError` rather than being
clamped — see :meth:`RuntimeSettings._reject_non_positive_timeout`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from publisher_v2.core.exceptions import ConfigurationError


def _float_env(name: str, default: float | None) -> float | None:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _bool_env(name: str, default: str, truthy: tuple[str, ...], *, strip: bool = False) -> bool:
    """Truthy-string parsing. ``truthy`` and ``strip`` differ per var — the old call sites did not agree.

    ``strip`` reproduces ``web/auth.py::_get_env``, which stripped the value and
    treated a whitespace-only one as unset. The call sites that used a bare
    ``os.environ.get`` must keep ``strip=False``, or a padded value would change
    meaning relative to the behaviour they had before #143.
    """
    raw = os.environ.get(name) or ""
    if strip:
        raw = raw.strip()
    return (raw or default).lower() in truthy


def _int_env(name: str, default: int | None) -> int | None:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class RuntimeSettings(BaseModel):
    """Runtime tunables. Optional fields fall back to static config at the call site.

    Frozen: one instance is shared by every request in the process (#143), so a
    component must not be able to mutate the snapshot its neighbours read.

    Build a variant with ``model_copy(update=...)``, bearing in mind that it
    does **not** re-run validation: a plain dict passed for
    ``publish_timeout_overrides`` is stored as-is, mutable and of the declared
    type's opposite shape. ``publish_timeout_for`` tolerates that, but the
    result is no longer immutable — construct a new instance when that matters.
    """

    model_config = ConfigDict(frozen=True)

    ai_rate_per_minute: int | None = None
    publish_timeout_seconds: float = 120.0
    ai_stage_timeout_seconds: float = 150.0
    publish_lease_ttl_seconds: float = 600.0
    web_image_cache_ttl_seconds: float | None = None
    caption_history_retention_days: int = 90
    tenant_service_cache_max_size: int = 1000
    tenant_service_ttl_seconds: int = 600
    library_max_upload_mb: int = 20
    library_scan_budget: int = 5000
    # A tuple of pairs, not a dict: the snapshot is shared process-wide, and a
    # dict field stays writable through its items even under ``frozen=True``.
    # A MappingProxyType would also be immutable but is neither picklable,
    # deep-copyable nor JSON-serialisable, which would make an ordinary
    # ``model_dump_json()`` or ``model_copy(deep=True)`` raise. Construct it
    # from a plain mapping; the validator below converts.
    publish_timeout_overrides: tuple[tuple[str, float], ...] = ()
    # #143: web/service-layer tunables that used to be ad-hoc os.environ reads.
    thumbnail_cache_ttl_seconds: float = 900.0
    thumbnail_cache_max_bytes: int = 50 * 1024 * 1024
    trust_forwarded_for: bool = False
    secure_cookies: bool = True
    config_source: str = ""
    orchestrator_base_url: str = ""
    # PUB-047 #186: asyncpg connect/command budgets and the publish-claim budget.
    # Positive values are deliberately unclamped, unlike publish_timeout_seconds —
    # a very small value is a legitimate way to fail fast (and is what the AC8
    # tests drive). ``<= 0`` is rejected outright by ``_reject_non_positive_timeout``
    # below: it is a misconfiguration, not a tunable.
    db_connect_timeout_seconds: float = 10.0
    db_command_timeout_seconds: float = 30.0
    publish_claim_timeout_seconds: float = 10.0

    @field_validator("publish_timeout_overrides", mode="before")
    @classmethod
    def _as_pairs(cls, value: object) -> object:
        """Accept the natural ``{"telegram": 30.0}`` form and store it immutably."""
        if isinstance(value, Mapping):
            return tuple(value.items())
        return value

    @field_validator("db_connect_timeout_seconds", "db_command_timeout_seconds", "publish_claim_timeout_seconds")
    @classmethod
    def _reject_non_positive_timeout(cls, value: float, info: ValidationInfo) -> float:
        """Reject ``<= 0`` budgets; positive values (however small) pass through unclamped.

        ``PUBLISH_CLAIM_TIMEOUT_SECONDS=0`` makes ``asyncio.wait_for`` fire on the
        first suspension, so every run aborts with ``publish_store_unavailable``
        for a store outage that does not exist; ``DB_CONNECT_TIMEOUT_SECONDS=0``
        hands asyncpg ``timeout=0``. Fail loudly at construction instead.
        """
        if value <= 0:
            raise ConfigurationError(f"{info.field_name} must be greater than 0 (got {value!r})")
        return value

    @property
    def is_standalone(self) -> bool:
        """Env-first mode: explicitly selected, or no orchestrator configured."""
        return self.config_source == "env" or not self.orchestrator_base_url

    def publish_timeout_for(self, platform: str) -> float:
        """Per-platform publish timeout, e.g. ``PUBLISH_TIMEOUT_TELEGRAM_SECONDS=30``."""
        wanted = platform.lower()
        # ``model_copy(update=...)`` and ``model_construct`` skip validation, so
        # this field can hold the plain mapping they were handed. Iterating that
        # would unpack its *keys* — raising, or worse, silently matching nothing
        # when a platform name happens to be two characters long.
        overrides = self.publish_timeout_overrides
        pairs = overrides.items() if isinstance(overrides, Mapping) else overrides
        for name, timeout in pairs:
            if name == wanted:
                return timeout
        return self.publish_timeout_seconds


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

    # 0 is a meaningful value for both (disable cache / unlimited), so no ``or`` fallback.
    thumb_ttl = _float_env("WEB_THUMBNAIL_CACHE_TTL_SECONDS", defaults.thumbnail_cache_ttl_seconds)
    thumb_max = _int_env("WEB_THUMBNAIL_CACHE_MAX_BYTES", defaults.thumbnail_cache_max_bytes)

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

    lease_ttl = _float_env("PUBLISH_LEASE_TTL_SECONDS", defaults.publish_lease_ttl_seconds)
    # #139: a lease older than this is assumed orphaned (its holder crashed) and
    # becomes reclaimable. The floor is the longest a healthy run can legitimately
    # hold a lease — the AI stage plus the slowest publish — with a margin; below
    # that, a second run could reclaim a live lease mid-publish and double-post.
    lease_floor = ai_stage + max([publish_timeout, *overrides.values()]) + 60.0
    lease_ttl = max(lease_floor, lease_ttl or defaults.publish_lease_ttl_seconds)

    # PUB-047 #186: positive values are passed through unclamped on purpose; a
    # ``<= 0`` value is rejected by the field validator, not silently floored.
    db_connect_timeout = _float_env("DB_CONNECT_TIMEOUT_SECONDS", defaults.db_connect_timeout_seconds)
    db_command_timeout = _float_env("DB_COMMAND_TIMEOUT_SECONDS", defaults.db_command_timeout_seconds)
    publish_claim_timeout = _float_env("PUBLISH_CLAIM_TIMEOUT_SECONDS", defaults.publish_claim_timeout_seconds)

    return RuntimeSettings(
        ai_rate_per_minute=rate,
        publish_timeout_seconds=publish_timeout,
        ai_stage_timeout_seconds=ai_stage,
        publish_lease_ttl_seconds=lease_ttl,
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
        publish_timeout_overrides=tuple(overrides.items()),
        thumbnail_cache_ttl_seconds=defaults.thumbnail_cache_ttl_seconds if thumb_ttl is None else thumb_ttl,
        thumbnail_cache_max_bytes=defaults.thumbnail_cache_max_bytes if thumb_max is None else thumb_max,
        # WEB_TRUST_FORWARDED_FOR historically did not accept "on"; keep it that way.
        trust_forwarded_for=_bool_env("WEB_TRUST_FORWARDED_FOR", "", ("1", "true", "yes")),
        # set_admin_cookie read this through web/auth.py::_get_env, which stripped:
        # "true " (a padded Heroku config var) has always meant on, and must keep
        # meaning on — otherwise the admin cookie silently loses its Secure flag.
        secure_cookies=_bool_env("WEB_SECURE_COOKIES", "true", ("1", "true", "yes", "on"), strip=True),
        config_source=(os.environ.get("CONFIG_SOURCE") or "").strip().lower(),
        orchestrator_base_url=os.environ.get("ORCHESTRATOR_BASE_URL") or "",
        db_connect_timeout_seconds=defaults.db_connect_timeout_seconds
        if db_connect_timeout is None
        else db_connect_timeout,
        db_command_timeout_seconds=defaults.db_command_timeout_seconds
        if db_command_timeout is None
        else db_command_timeout,
        publish_claim_timeout_seconds=defaults.publish_claim_timeout_seconds
        if publish_claim_timeout is None
        else publish_claim_timeout,
    )
