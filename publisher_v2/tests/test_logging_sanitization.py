"""
Tests for log sanitization to prevent secret leaks.

Security-critical: Ensures sensitive data (tokens, keys, passwords) are redacted
from ALL log output, including third-party library logs.
"""

from __future__ import annotations

import logging
import pytest

from publisher_v2.utils.logging import sanitize, SanitizingFilter, setup_logging


class TestSanitizeFunction:
    """Tests for the sanitize() function."""

    def test_redacts_openai_api_key(self):
        """OpenAI API keys should be redacted."""
        msg = "Using API key sk-proj-abc123xyz789abcdefghijk"
        assert "sk-proj-" not in sanitize(msg)
        assert "[OPENAI_KEY_REDACTED]" in sanitize(msg)

    def test_redacts_telegram_bot_token(self):
        """Telegram bot tokens (format: 123456:ABC-xyz) should be redacted."""
        msg = "Bot token: 123456789:ABC-xyz_123def456ghi"
        assert "123456789:" not in sanitize(msg)
        assert "[TELEGRAM_TOKEN_REDACTED]" in sanitize(msg)

    def test_redacts_telegram_api_url(self):
        """Telegram API URLs containing bot tokens should be redacted."""
        # This is what httpx logs when making Telegram API requests
        msg = "HTTP Request: POST https://api.telegram.org/bot123456789:ABC-xyz_123def456ghi/sendPhoto"
        sanitized = sanitize(msg)
        assert "123456789:" not in sanitized
        assert "api.telegram.org/bot[REDACTED]" in sanitized

    def test_redacts_dropbox_token(self):
        """Dropbox access tokens should be redacted."""
        # Dropbox tokens start with 'sl.' and are very long
        token = "sl." + "a" * 150
        msg = f"Dropbox token: {token}"
        assert token not in sanitize(msg)
        assert "[DROPBOX_TOKEN_REDACTED]" in sanitize(msg)

    def test_preserves_normal_messages(self):
        """Non-sensitive messages should pass through unchanged."""
        msg = "Processing image: test.jpg in /Photos folder"
        assert sanitize(msg) == msg

    def test_multiple_secrets_in_one_message(self):
        """Multiple secrets in one message should all be redacted."""
        msg = "OpenAI: sk-proj-abc123xyz789abcdefghijk, Telegram: 123456789:ABC-xyz_123def456ghi"
        sanitized = sanitize(msg)
        assert "sk-proj-" not in sanitized
        assert "123456789:" not in sanitized
        assert "[OPENAI_KEY_REDACTED]" in sanitized
        assert "[TELEGRAM_TOKEN_REDACTED]" in sanitized


class TestSanitizingFilter:
    """Tests for the SanitizingFilter logging filter."""

    def test_filter_sanitizes_message(self):
        """Filter should sanitize the log record message."""
        filter = SanitizingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Token: 123456789:ABC-xyz_123def456ghi",
            args=(),
            exc_info=None,
        )
        filter.filter(record)
        assert "123456789:" not in record.msg
        assert "[TELEGRAM_TOKEN_REDACTED]" in record.msg

    def test_filter_sanitizes_string_args(self):
        """Filter should sanitize string arguments."""
        filter = SanitizingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Request to %s",
            args=("https://api.telegram.org/bot123456789:ABC-xyz/sendPhoto",),
            exc_info=None,
        )
        filter.filter(record)
        assert "123456789:" not in str(record.args)

    def test_filter_always_returns_true(self):
        """Filter should always return True (allow message through after sanitization)."""
        filter = SanitizingFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        assert filter.filter(record) is True


class TestSetupLogging:
    """Tests for setup_logging configuration."""

    def test_setup_adds_sanitizing_filter(self):
        """setup_logging should add SanitizingFilter to the root handler."""
        setup_logging(logging.INFO)
        root = logging.getLogger()
        
        # Check that at least one handler has a SanitizingFilter
        has_sanitizing_filter = False
        for handler in root.handlers:
            for filter in handler.filters:
                if isinstance(filter, SanitizingFilter):
                    has_sanitizing_filter = True
                    break
        
        assert has_sanitizing_filter, "Root logger should have SanitizingFilter attached"

    def test_setup_reduces_httpx_verbosity(self):
        """setup_logging should reduce httpx/httpcore log levels."""
        setup_logging(logging.INFO)
        
        assert logging.getLogger("httpx").level >= logging.WARNING
        assert logging.getLogger("httpcore").level >= logging.WARNING
        assert logging.getLogger("telegram").level >= logging.WARNING

