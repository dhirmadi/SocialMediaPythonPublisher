"""Tests for JSON parsing helpers in config/loader.py (Story 021-01)."""

import os
from unittest.mock import patch

import pytest

from publisher_v2.config.loader import (
    REDACT_KEYS,
    _parse_json_env,
    _safe_log_config,
)
from publisher_v2.core.exceptions import ConfigurationError


class TestParseJsonEnv:
    """Tests for _parse_json_env() function."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            pytest.param('{"key": "value", "num": 42}', {"key": "value", "num": 42}, id="object"),
            pytest.param('[1, 2, "three"]', [1, 2, "three"], id="array"),
            pytest.param('{"nested": {"a": 1}, "list": [1, 2]}', {"nested": {"a": 1}, "list": [1, 2]}, id="nested"),
            pytest.param('{"emoji": "🎉", "text": "日本語"}', {"emoji": "🎉", "text": "日本語"}, id="unicode"),
        ],
    )
    def test_parse_valid_json(self, raw: str, expected: object) -> None:
        """Valid JSON (object, array, nested, unicode) is parsed and returned."""
        with patch.dict(os.environ, {"TEST_VAR": raw}):
            assert _parse_json_env("TEST_VAR") == expected

    def test_parse_invalid_json_raises_config_error(self):
        """Invalid JSON raises ConfigurationError with position info."""
        with patch.dict(os.environ, {"TEST_VAR": '{"key": }'}):
            with pytest.raises(ConfigurationError) as exc_info:
                _parse_json_env("TEST_VAR")
            assert "Invalid JSON in TEST_VAR" in str(exc_info.value)
            assert "position" in str(exc_info.value)

    def test_parse_invalid_json_unclosed_brace(self):
        """Unclosed brace raises ConfigurationError."""
        with patch.dict(os.environ, {"TEST_VAR": '{"key": "value"'}):
            with pytest.raises(ConfigurationError) as exc_info:
                _parse_json_env("TEST_VAR")
            assert "Invalid JSON in TEST_VAR" in str(exc_info.value)

    def test_parse_unset_env_var_returns_none(self):
        """Unset environment variable returns None."""
        # Ensure the var doesn't exist
        env = os.environ.copy()
        env.pop("NONEXISTENT_VAR", None)
        with patch.dict(os.environ, env, clear=True):
            result = _parse_json_env("NONEXISTENT_VAR")
            assert result is None

    @pytest.mark.parametrize("raw", ["", "   \t\n  "], ids=["empty", "whitespace-only"])
    def test_parse_blank_env_var_returns_none(self, raw: str) -> None:
        """An empty or whitespace-only value returns None."""
        with patch.dict(os.environ, {"TEST_VAR": raw}):
            assert _parse_json_env("TEST_VAR") is None


class TestSafeLogConfig:
    """Tests for _safe_log_config() function."""

    @pytest.mark.parametrize(
        ("secret_key", "secret", "other_key", "other"),
        [
            ("password", "secret123", "name", "test"),
            ("bot_token", "123:abc", "channel", "-100"),
            ("api_key", "sk-123456", "model", "gpt-4"),
            ("refresh_token", "token123", "app_key", "app123"),
            ("secret", "mysecret", "public", "mypublic"),
            ("token", "abc123", "id", "user1"),
        ],
    )
    def test_redacts_sensitive_key(self, secret_key: str, secret: str, other_key: str, other: str) -> None:
        """A sensitive key is redacted; the neighbouring non-sensitive key is kept."""
        result = _safe_log_config({secret_key: secret, other_key: other})
        assert result[secret_key] == "***REDACTED***"
        assert result[other_key] == other

    def test_keeps_non_sensitive_keys(self):
        """Non-sensitive keys are not redacted."""
        cfg = {"name": "test", "email": "test@example.com", "port": 587}
        result = _safe_log_config(cfg)
        assert result == cfg

    def test_case_insensitive_redaction(self):
        """Redaction is case-insensitive."""
        cfg = {"PASSWORD": "secret", "Password": "secret2", "pAsSwOrD": "secret3"}
        result = _safe_log_config(cfg)
        assert result["PASSWORD"] == "***REDACTED***"
        assert result["Password"] == "***REDACTED***"
        assert result["pAsSwOrD"] == "***REDACTED***"

    def test_original_dict_not_modified(self):
        """Original dict is not modified."""
        cfg = {"password": "secret", "name": "test"}
        _safe_log_config(cfg)
        assert cfg["password"] == "secret"

    def test_custom_redact_keys(self):
        """Custom redact keys can be provided."""
        cfg = {"custom_secret": "value", "password": "ignored"}
        result = _safe_log_config(cfg, redact_keys={"custom_secret"})
        assert result["custom_secret"] == "***REDACTED***"
        assert result["password"] == "ignored"  # Not in custom set

    def test_empty_dict(self):
        """Empty dict returns empty dict."""
        result = _safe_log_config({})
        assert result == {}


class TestRedactKeys:
    """Tests for REDACT_KEYS constant."""

    def test_redact_keys_contains_expected_keys(self):
        """REDACT_KEYS contains all expected sensitive key names.

        Exact equality on purpose: this is a change detector for a security
        constant, so adding a key here must be a deliberate edit. PUB-050 added
        ``voice_profile_tags`` — ``_safe_log_config`` matches keys by exact
        lowercase equality, not substring, so the tags map would otherwise be
        logged in the clear beside a redacted ``voice_profile``.
        """
        expected = {
            "password",
            "secret",
            "token",
            "refresh_token",
            "bot_token",
            "api_key",
            "voice_profile",
            "voice_profile_tags",
        }
        assert expected == REDACT_KEYS
