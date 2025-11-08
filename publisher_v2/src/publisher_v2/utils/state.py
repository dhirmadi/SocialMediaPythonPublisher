from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Set


def _cache_path() -> Path:
    # Store under user cache directory
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(Path.home(), ".cache")
    path = Path(base) / "publisher_v2"
    path.mkdir(parents=True, exist_ok=True)
    return path / "posted.json"


def load_posted_hashes() -> Set[str]:
    fp = _cache_path()
    if not fp.exists():
        return set()
    try:
        data = json.loads(fp.read_text())
        if isinstance(data, list):
            return set(str(x) for x in data)
        if isinstance(data, dict) and "hashes" in data:
            return set(str(x) for x in data["hashes"])
    except Exception:
        return set()
    return set()


def save_posted_hash(hash_value: str) -> None:
    hashes = load_posted_hashes()
    if hash_value in hashes:
        return
    hashes.add(hash_value)
    fp = _cache_path()
    try:
        fp.write_text(json.dumps(sorted(hashes)))
    except Exception:
        # Best-effort; ignore failures
        pass


