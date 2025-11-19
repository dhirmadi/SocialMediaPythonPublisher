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



