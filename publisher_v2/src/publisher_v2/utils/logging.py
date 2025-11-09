from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict
import re

SENSITIVE_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "[OPENAI_KEY_REDACTED]"),
    (re.compile(r"r8_[A-Za-z0-9]+"), "[REPLICATE_TOKEN_REDACTED]"),
    (re.compile(r"[0-9]{6,}:[A-Za-z0-9_-]{20,}"), "[TELEGRAM_TOKEN_REDACTED]"),
]


def sanitize(message: str) -> str:
    sanitized = message
    for pattern, repl in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(repl, sanitized)
    return sanitized


def setup_logging(level: int = logging.INFO) -> None:
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(level)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console)


def log_json(logger: logging.Logger, level: int, message: str, **kwargs: Any) -> None:
    entry: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": sanitize(message),
        **kwargs,
    }
    logger.log(level, json.dumps(entry))


