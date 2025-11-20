from __future__ import annotations

import json
from typing import Tuple, Dict, Any, Optional


def parse_sidecar_text(text: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Parse a caption sidecar text into (sd_caption, metadata_dict).

    Current writer format (see utils.captions.build_caption_sidecar):
      - First line: sd_caption
      - Blank line
      - '# ---'
      - '# key: value' lines, arrays encoded as JSON arrays

    If parsing fails, returns (sd_caption_or_none, None) and leaves
    error handling to the caller.
    """
    if not text:
        return None, None

    lines = text.splitlines()
    if not lines:
        return None, None

    sd_caption = lines[0].strip() or None

    # Look for metadata header '# ---'
    meta_start = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip().startswith("# ---"):
            meta_start = idx + 1
            break

    if meta_start is None or meta_start >= len(lines):
        return sd_caption, None

    meta: Dict[str, Any] = {}
    for line in lines[meta_start:]:
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("# "):
            continue
        body = stripped[2:]
        if ": " not in body:
            continue
        key, raw_value = body.split(": ", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            continue
        # Try to decode JSON arrays/objects, otherwise keep as string
        if raw_value.startswith("[") or raw_value.startswith("{"):
            try:
                value = json.loads(raw_value)
            except json.JSONDecodeError:
                value = raw_value
        else:
            value = raw_value
        meta[key] = value

    if not meta:
        return sd_caption, None
    return sd_caption, meta


def rehydrate_sidecar_view(text: str) -> Dict[str, Any]:
    """
    Construct a lightweight, cache-ready view from raw sidecar text.

    Returns a dict with keys:
      - sd_caption: Optional[str]
      - caption: Optional[str] (metadata caption if present, otherwise sd_caption)
      - metadata: Optional[dict[str, Any]]
      - has_sidecar: bool

    This helper encapsulates canonical "sidecars as cache" semantics for the web
    layer and other callers that do not need a full ImageAnalysis instance.
    """
    sd_caption, metadata = parse_sidecar_text(text)
    caption: Optional[str] = None
    if isinstance(metadata, dict):
        raw_caption = metadata.get("caption")
        if isinstance(raw_caption, str):
            raw_caption = raw_caption.strip()
            if raw_caption:
                caption = raw_caption
    if caption is None:
        caption = sd_caption
    has_sidecar = bool(sd_caption or metadata)
    return {
        "sd_caption": sd_caption,
        "caption": caption,
        "metadata": metadata,
        "has_sidecar": has_sidecar,
    }


