from __future__ import annotations

import re


_MAX_LEN = {
    "instagram": 2200,
    "telegram": 4096,
    "email": 240,  # FetLife email path: keep within ~240 to avoid truncation
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


def _sanitize_for_fetlife(text: str) -> str:
    """
    Normalize punctuation and unicode that FetLife may strip, to preserve spacing and readability.
    Examples:
      - em/en dashes → ' - ' so 'trust—what' becomes 'trust - what'
      - smart quotes → ASCII quotes
      - ellipsis char → '...'
      - collapse any excessive whitespace after replacements
    """
    # Dashes: em (—), en (–), minus (−)
    text = re.sub(r"[—–−]", " - ", text)
    # Smart quotes
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    # Ellipsis
    text = text.replace("…", "...")
    # Zero-width and non-breaking spaces to regular space
    text = text.replace("\u200b", " ").replace("\u00a0", " ")
    # Collapse multiple spaces created by replacements
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def format_caption(platform: str, caption: str) -> str:
    p = platform.lower()
    max_len = _MAX_LEN.get(p, _MAX_LEN["generic"])
    formatted = caption.strip()
    if p == "instagram":
        formatted = _limit_instagram_hashtags(formatted)
    elif p == "email":
        # FetLife email path: strip all hashtags entirely
        formatted = re.sub(r"#\w+", "", formatted)
        formatted = _sanitize_for_fetlife(formatted)
    # Telegram can keep as-is (supports 4096 chars)
    formatted = _trim_to_length(formatted, max_len)
    return formatted


