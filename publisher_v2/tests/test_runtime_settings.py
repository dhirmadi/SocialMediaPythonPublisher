"""#97 stage 2: centralized runtime settings (config/runtime_settings.py).

Every remaining ad-hoc ``os.environ`` tunable moves behind
``load_runtime_settings()``; call sites receive values instead of reading env.
"""

from __future__ import annotations

import pytest

from publisher_v2.config.runtime_settings import RuntimeSettings, load_runtime_settings
from publisher_v2.core.exceptions import ConfigurationError

_ENV_KEYS = [
    "AI_RATE_PER_MINUTE",
    "PUBLISH_TIMEOUT_SECONDS",
    "AI_STAGE_TIMEOUT_SECONDS",
    "PUBLISH_TIMEOUT_TELEGRAM_SECONDS",
    "WEB_IMAGE_CACHE_TTL_SECONDS",
    "PV2_CAPTION_HISTORY_RETENTION_DAYS",
    "TENANT_SERVICE_CACHE_MAX_SIZE",
    "TENANT_SERVICE_TTL_SECONDS",
    "LIBRARY_MAX_UPLOAD_MB",
    "LIBRARY_SCAN_BUDGET",
    # PUB-047 #186 (AC7): Postgres + publish-claim budgets.
    "DB_CONNECT_TIMEOUT_SECONDS",
    "DB_COMMAND_TIMEOUT_SECONDS",
    "PUBLISH_CLAIM_TIMEOUT_SECONDS",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


class TestDefaults:
    def test_defaults_match_previous_call_site_defaults(self) -> None:
        s = load_runtime_settings()
        assert s.ai_rate_per_minute is None  # falls back to static config at the call site
        assert s.publish_timeout_seconds == 120.0
        assert s.ai_stage_timeout_seconds == 150.0
        assert s.web_image_cache_ttl_seconds is None  # falls back to static config
        assert s.caption_history_retention_days == 90
        assert s.tenant_service_cache_max_size == 1000
        assert s.tenant_service_ttl_seconds == 600
        assert s.library_max_upload_mb == 20
        assert s.library_scan_budget == 5000


class TestEnvParsing:
    def test_each_env_var_is_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_RATE_PER_MINUTE", "7")
        monkeypatch.setenv("PUBLISH_TIMEOUT_SECONDS", "30")
        monkeypatch.setenv("AI_STAGE_TIMEOUT_SECONDS", "9.5")
        monkeypatch.setenv("WEB_IMAGE_CACHE_TTL_SECONDS", "2.5")
        monkeypatch.setenv("PV2_CAPTION_HISTORY_RETENTION_DAYS", "30")
        monkeypatch.setenv("TENANT_SERVICE_CACHE_MAX_SIZE", "5")
        monkeypatch.setenv("TENANT_SERVICE_TTL_SECONDS", "60")
        monkeypatch.setenv("LIBRARY_MAX_UPLOAD_MB", "8")
        monkeypatch.setenv("LIBRARY_SCAN_BUDGET", "100")

        s = load_runtime_settings()
        assert s.ai_rate_per_minute == 7
        assert s.publish_timeout_seconds == 30.0
        assert s.ai_stage_timeout_seconds == 9.5
        assert s.web_image_cache_ttl_seconds == 2.5
        assert s.caption_history_retention_days == 30
        assert s.tenant_service_cache_max_size == 5
        assert s.tenant_service_ttl_seconds == 60
        assert s.library_max_upload_mb == 8
        assert s.library_scan_budget == 100

    def test_invalid_values_fall_back_to_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key in _ENV_KEYS:
            monkeypatch.setenv(key, "not-a-number")
        s = load_runtime_settings()
        assert s == RuntimeSettings()

    def test_clamps_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Previous call sites clamped: publish >= 5s, ai stage >= 0.1s.
        monkeypatch.setenv("PUBLISH_TIMEOUT_SECONDS", "1")
        monkeypatch.setenv("AI_STAGE_TIMEOUT_SECONDS", "0.001")
        s = load_runtime_settings()
        assert s.publish_timeout_seconds == 5.0
        assert s.ai_stage_timeout_seconds == 0.1

    def test_nonpositive_optional_values_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_RATE_PER_MINUTE", "0")
        monkeypatch.setenv("WEB_IMAGE_CACHE_TTL_SECONDS", "-1")
        s = load_runtime_settings()
        assert s.ai_rate_per_minute is None
        assert s.web_image_cache_ttl_seconds is None


class TestPerPlatformPublishTimeout:
    def test_platform_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PUBLISH_TIMEOUT_TELEGRAM_SECONDS", "30")
        s = load_runtime_settings()
        assert s.publish_timeout_for("telegram") == 30.0
        assert s.publish_timeout_for("email") == s.publish_timeout_seconds

    def test_platform_override_clamped_and_validated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PUBLISH_TIMEOUT_TELEGRAM_SECONDS", "1")
        monkeypatch.setenv("PUBLISH_TIMEOUT_EMAIL_SECONDS", "junk")
        s = load_runtime_settings()
        assert s.publish_timeout_for("telegram") == 5.0
        assert s.publish_timeout_for("email") == s.publish_timeout_seconds


class TestDbAndClaimTimeouts:
    """PUB-047 #186 (AC7): new DB + publish-claim budgets, lenient parse, no clamping."""

    def test_db_timeout_fields_read_from_env_with_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        defaults = load_runtime_settings()
        assert defaults.db_connect_timeout_seconds == 10.0
        assert defaults.db_command_timeout_seconds == 30.0
        assert defaults.publish_claim_timeout_seconds == 10.0

        monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "2.5")
        monkeypatch.setenv("DB_COMMAND_TIMEOUT_SECONDS", "45")
        monkeypatch.setenv("PUBLISH_CLAIM_TIMEOUT_SECONDS", "0.25")
        s = load_runtime_settings()
        assert s.db_connect_timeout_seconds == 2.5
        assert s.db_command_timeout_seconds == 45.0
        # No clamping is specified for these three (contrast publish_timeout_seconds' 5s floor).
        assert s.publish_claim_timeout_seconds == 0.25

        # Lenient _float_env: an unparseable value falls back to the default, never raises.
        monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "not-a-number")
        monkeypatch.setenv("DB_COMMAND_TIMEOUT_SECONDS", "")
        monkeypatch.setenv("PUBLISH_CLAIM_TIMEOUT_SECONDS", "junk")
        fallback = load_runtime_settings()
        assert fallback.db_connect_timeout_seconds == 10.0
        assert fallback.db_command_timeout_seconds == 30.0
        assert fallback.publish_claim_timeout_seconds == 10.0

    @pytest.mark.parametrize(
        "field",
        ["db_connect_timeout_seconds", "db_command_timeout_seconds", "publish_claim_timeout_seconds"],
    )
    @pytest.mark.parametrize("bad", [0, 0.0, -1.0, -0.001])
    def test_non_positive_timeouts_are_rejected(self, field: str, bad: float) -> None:
        """PUB-047 review item 4: 0 or negative is a misconfiguration, not a tunable.

        ``PUBLISH_CLAIM_TIMEOUT_SECONDS=0`` makes ``asyncio.wait_for`` fire on the
        first suspension, so every run reports ``publish_store_unavailable`` for a
        store outage that does not exist; ``DB_CONNECT_TIMEOUT_SECONDS=0`` hands
        asyncpg ``timeout=0``. Reject at construction rather than clamping.
        """
        with pytest.raises(ConfigurationError):
            RuntimeSettings(**{field: bad})

    @pytest.mark.parametrize(
        "env_key",
        ["DB_CONNECT_TIMEOUT_SECONDS", "DB_COMMAND_TIMEOUT_SECONDS", "PUBLISH_CLAIM_TIMEOUT_SECONDS"],
    )
    def test_non_positive_timeout_env_values_are_rejected(self, env_key: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """A ``0`` in the environment must fail loudly at load, not silently disable the budget."""
        monkeypatch.setenv(env_key, "0")
        with pytest.raises(ConfigurationError):
            load_runtime_settings()

        monkeypatch.setenv(env_key, "-5")
        with pytest.raises(ConfigurationError):
            load_runtime_settings()

    def test_small_positive_timeouts_are_still_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reject, do not clamp: AC8's hang tests drive a real, very small timeout."""
        monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "0.001")
        monkeypatch.setenv("DB_COMMAND_TIMEOUT_SECONDS", "0.001")
        monkeypatch.setenv("PUBLISH_CLAIM_TIMEOUT_SECONDS", "0.001")
        s = load_runtime_settings()

        assert s.db_connect_timeout_seconds == 0.001
        assert s.db_command_timeout_seconds == 0.001
        assert s.publish_claim_timeout_seconds == 0.001
