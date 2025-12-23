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

    def test_parse_valid_json_object(self):
        """Valid JSON object is parsed and returned as dict."""
        with patch.dict(os.environ, {"TEST_VAR": '{"key": "value", "num": 42}'}):
            result = _parse_json_env("TEST_VAR")
            assert result == {"key": "value", "num": 42}

    def test_parse_valid_json_array(self):
        """Valid JSON array is parsed and returned as list."""
        with patch.dict(os.environ, {"TEST_VAR": '[1, 2, "three"]'}):
            result = _parse_json_env("TEST_VAR")
            assert result == [1, 2, "three"]

    def test_parse_valid_json_nested(self):
        """Nested JSON structures are parsed correctly."""
        with patch.dict(os.environ, {"TEST_VAR": '{"nested": {"a": 1}, "list": [1, 2]}'}):
            result = _parse_json_env("TEST_VAR")
            assert result == {"nested": {"a": 1}, "list": [1, 2]}

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

    def test_parse_empty_env_var_returns_none(self):
        """Empty string returns None."""
        with patch.dict(os.environ, {"TEST_VAR": ""}):
            result = _parse_json_env("TEST_VAR")
            assert result is None

    def test_parse_whitespace_only_returns_none(self):
        """Whitespace-only string returns None."""
        with patch.dict(os.environ, {"TEST_VAR": "   \t\n  "}):
            result = _parse_json_env("TEST_VAR")
            assert result is None

    def test_parse_json_with_unicode(self):
        """JSON with unicode characters is parsed correctly."""
        with patch.dict(os.environ, {"TEST_VAR": '{"emoji": "🎉", "text": "日本語"}'}):
            result = _parse_json_env("TEST_VAR")
            assert result == {"emoji": "🎉", "text": "日本語"}


class TestSafeLogConfig:
    """Tests for _safe_log_config() function."""

    def test_redacts_password_key(self):
        """Password key is redacted."""
        cfg = {"password": "secret123", "name": "test"}
        result = _safe_log_config(cfg)
        assert result["password"] == "***REDACTED***"
        assert result["name"] == "test"

    def test_redacts_bot_token_key(self):
        """bot_token key is redacted."""
        cfg = {"bot_token": "123:abc", "channel": "-100"}
        result = _safe_log_config(cfg)
        assert result["bot_token"] == "***REDACTED***"
        assert result["channel"] == "-100"

    def test_redacts_api_key(self):
        """api_key is redacted."""
        cfg = {"api_key": "sk-123456", "model": "gpt-4"}
        result = _safe_log_config(cfg)
        assert result["api_key"] == "***REDACTED***"
        assert result["model"] == "gpt-4"

    def test_redacts_refresh_token(self):
        """refresh_token is redacted."""
        cfg = {"refresh_token": "token123", "app_key": "app123"}
        result = _safe_log_config(cfg)
        assert result["refresh_token"] == "***REDACTED***"

    def test_redacts_secret_key(self):
        """secret key is redacted."""
        cfg = {"secret": "mysecret", "public": "mypublic"}
        result = _safe_log_config(cfg)
        assert result["secret"] == "***REDACTED***"
        assert result["public"] == "mypublic"

    def test_redacts_token_key(self):
        """token key is redacted."""
        cfg = {"token": "abc123", "id": "user1"}
        result = _safe_log_config(cfg)
        assert result["token"] == "***REDACTED***"
        assert result["id"] == "user1"

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
        """REDACT_KEYS contains all expected sensitive key names."""
        expected = {"password", "secret", "token", "refresh_token", "bot_token", "api_key"}
        assert REDACT_KEYS == expected

    def test_redact_keys_is_set(self):
        """REDACT_KEYS is a set for O(1) lookup."""
        assert isinstance(REDACT_KEYS, set)

