from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict
import re
import time

# Patterns to redact sensitive data from ALL log output
SENSITIVE_PATTERNS = [
    # OpenAI API keys: sk-xxx, sk-proj-xxx, sk-org-xxx (new formats include hyphens)
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "[OPENAI_KEY_REDACTED]"),
    (re.compile(r"r8_[A-Za-z0-9]+"), "[REPLICATE_TOKEN_REDACTED]"),
    # Telegram bot token format: 123456789:ABC-xyz (digits:alphanumeric)
    (re.compile(r"[0-9]{6,}:[A-Za-z0-9_-]{20,}"), "[TELEGRAM_TOKEN_REDACTED]"),
    # Telegram API URLs containing bot token
    (re.compile(r"api\.telegram\.org/bot[^/\s]+"), "api.telegram.org/bot[REDACTED]"),
    # Dropbox tokens (start with sl.)
    (re.compile(r"sl\.[A-Za-z0-9_-]{100,}"), "[DROPBOX_TOKEN_REDACTED]"),
]


def sanitize(message: str) -> str:
    """Redact sensitive patterns from a string."""
    sanitized = message
    for pattern, repl in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(repl, sanitized)
    return sanitized


class SanitizingFilter(logging.Filter):
    """
    Logging filter that redacts sensitive data from ALL log records.
    
    This filter applies sanitization to:
    - The formatted message (record.msg after % formatting)
    - Any string arguments in record.args
    
    This catches secrets leaked by third-party libraries like httpx/httpcore
    that log HTTP URLs containing tokens.
    """
    
    def filter(self, record: logging.LogRecord) -> bool:
        # Sanitize the message
        if record.msg:
            if isinstance(record.msg, str):
                record.msg = sanitize(record.msg)
        
        # Sanitize args if they exist
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: sanitize(str(v)) if isinstance(v, str) else v for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(sanitize(str(a)) if isinstance(a, str) else a for a in record.args)
        
        return True  # Always allow the record through (after sanitization)


def setup_logging(level: int = logging.INFO) -> None:
    """
    Configure logging with sanitization filter applied to ALL handlers.
    
    This ensures secrets are redacted from:
    - Our application logs
    - Third-party library logs (httpx, httpcore, telegram, etc.)
    """
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    # Create handler with sanitizing filter
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(level)
    console.addFilter(SanitizingFilter())  # Redact secrets from ALL output
    
    # Configure root logger
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console)
    
    # Reduce verbosity of HTTP client libraries (they log at INFO by default)
    # Even with sanitization, we don't need detailed HTTP logs in production
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)


def log_json(logger: logging.Logger, level: int, message: str, **kwargs: Any) -> None:
    entry: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": sanitize(message),
        **kwargs,
    }
    logger.log(level, json.dumps(entry))


def now_monotonic() -> float:
    """
    Return a monotonically increasing timestamp suitable for measuring durations.
    """
    return time.perf_counter()


def elapsed_ms(start: float) -> int:
    """
    Return the elapsed time in integer milliseconds since ``start``.
    """
    return int((time.perf_counter() - start) * 1000)


def log_publisher_publish(
    logger: logging.Logger,
    platform: str,
    start: float,
    success: bool,
    error: str | None = None,
) -> None:
    """
    Convenience helper to emit a structured per-publisher timing log.
    """

    duration_ms = elapsed_ms(start)
    level = logging.INFO if success else logging.ERROR
    log_json(
        logger,
        level,
        "publisher_publish",
        platform=platform,
        duration_ms=duration_ms,
        success=success,
        error=error,
    )


