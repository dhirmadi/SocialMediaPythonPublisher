from __future__ import annotations

import re


_MAX_LEN = {
    "instagram": 2200,
    "telegram": 4096,
    "email": 10000,  # subject handled separately
    "generic": 2200,
}


def _trim_to_length(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    # Favor keeping full hashtags at the end; truncate before trailing hashtags if possible
    parts = re.split(r"(\s#)", text)
    base = parts[0]
    if len(base) + 1 <= max_len:
        return (base[: max_len - 1]).rstrip() + "…"
    return text[: max_len - 1].rstrip() + "…"


def _limit_instagram_hashtags(text: str) -> str:
    hashtags = re.findall(r"#\w+", text)
    if len(hashtags) <= 30:
        return text
    # Keep the first 30, remove extras
    keep = set(hashtags[:30])
    def repl(m):
        return m.group(0) if m.group(0) in keep else ""
    text = re.sub(r"#\w+", repl, text)
    # Normalize spaces
    return re.sub(r"\s{2,}", " ", text).strip()


def format_caption(platform: str, caption: str) -> str:
    p = platform.lower()
    max_len = _MAX_LEN.get(p, _MAX_LEN["generic"])
    formatted = caption.strip()
    if p == "instagram":
        formatted = _limit_instagram_hashtags(formatted)
    # Telegram can keep as-is (supports 4096 chars)
    formatted = _trim_to_length(formatted, max_len)
    return formatted


