from __future__ import annotations

import json
import re
from typing import Any, Dict

from publisher_v2.core.models import ImageAnalysis


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


def build_metadata_phase1(
    image_file: str,
    sha256: str,
    created_iso: str,
    sd_caption_version: str,
    model_version: str,
    dropbox_file_id: str | None,
    dropbox_rev: str | None,
) -> Dict[str, Any]:
    """
    Build Phase 1 identity/version metadata. Omit missing fields.
    """
    meta: Dict[str, Any] = {}
    if image_file:
        meta["image_file"] = image_file
    if dropbox_file_id:
        meta["dropbox_file_id"] = dropbox_file_id
    if dropbox_rev:
        meta["dropbox_rev"] = dropbox_rev
    if sha256:
        meta["sha256"] = sha256
    if created_iso:
        meta["created"] = created_iso
    if sd_caption_version:
        meta["sd_caption_version"] = sd_caption_version
    if model_version:
        meta["model_version"] = model_version
    return meta


def build_metadata_phase2(analysis: ImageAnalysis) -> Dict[str, Any]:
    """
    Build Phase 2 contextual metadata from analysis. Omit missing/empty fields.
    """
    meta: Dict[str, Any] = {}
    if getattr(analysis, "lighting", None):
        meta["lighting"] = analysis.lighting
    if getattr(analysis, "pose", None):
        meta["pose"] = analysis.pose
    # Map 'materials' to clothing_or_accessories if present
    materials = getattr(analysis, "clothing_or_accessories", None)
    if materials:
        meta["materials"] = materials
    if getattr(analysis, "style", None):
        meta["art_style"] = analysis.style
    tags = getattr(analysis, "tags", None) or []
    if isinstance(tags, list) and tags:
        meta["tags"] = [str(t) for t in tags if str(t).strip()]
    moderation = getattr(analysis, "safety_labels", None) or []
    if isinstance(moderation, list) and moderation:
        meta["moderation"] = [str(m) for m in moderation if str(m).strip()]
    return meta


def build_caption_sidecar(sd_caption: str, metadata: Dict[str, Any]) -> str:
    """
    Compose the sidecar file content:
    - First line: sd_caption
    - Blank line
    - '# ---'
    - '# key: value' lines; arrays encoded as JSON arrays
    """
    lines: list[str] = []
    lines.append(sd_caption.strip())
    lines.append("")  # blank line
    lines.append("# ---")
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, list):
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = str(value)
        lines.append(f"# {key}: {rendered}")
    lines.append("")  # trailing newline
    return "\n".join(lines)

