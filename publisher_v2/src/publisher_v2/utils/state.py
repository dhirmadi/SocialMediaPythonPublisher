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


def _load_state() -> Dict[str, object]:
    """
    Internal helper to load posted state in a backward-compatible way.

    Supported formats:
    - Legacy list: ["sha1", "sha2", ...]
    - Dict legacy: {"hashes": ["sha1", "sha2", ...]}
    - Dict extended: {"hashes": [...], "dropbox_content_hashes": ["dbhash1", ...]}
    """
    fp = _cache_path()
    if not fp.exists():
        return {}
    try:
        raw = fp.read_text()
        if not raw:
            return {}
        data = json.loads(raw)
    except Exception:
        return {}

    if isinstance(data, list):
        return {"hashes": [str(x) for x in data]}
    if isinstance(data, dict):
        state: Dict[str, object] = {}
        hashes = data.get("hashes")
        if isinstance(hashes, list):
            state["hashes"] = [str(x) for x in hashes]
        content_hashes = data.get("dropbox_content_hashes")
        if isinstance(content_hashes, list):
            state["dropbox_content_hashes"] = [str(x) for x in content_hashes]
        return state
    return {}


def _save_state(state: Dict[str, object]) -> None:
    fp = _cache_path()
    try:
        fp.write_text(json.dumps(state, sort_keys=True))
    except Exception:
        # Best-effort; ignore failures
        pass


def load_posted_hashes() -> Set[str]:
    state = _load_state()
    hashes = state.get("hashes")
    if isinstance(hashes, list):
        return set(str(x) for x in hashes)
    return set()


def save_posted_hash(hash_value: str) -> None:
    state = _load_state()
    hashes = state.get("hashes")
    if not isinstance(hashes, list):
        hashes = []
    if hash_value in hashes:
        return
    hashes.append(hash_value)
    state["hashes"] = sorted(set(str(x) for x in hashes))
    _save_state(state)


def load_posted_content_hashes() -> Set[str]:
    state = _load_state()
    content_hashes = state.get("dropbox_content_hashes")
    if isinstance(content_hashes, list):
        return set(str(x) for x in content_hashes)
    return set()


def save_posted_content_hash(hash_value: str) -> None:
    if not hash_value:
        return
    state = _load_state()
    content_hashes = state.get("dropbox_content_hashes")
    if not isinstance(content_hashes, list):
        content_hashes = []
    if hash_value in content_hashes:
        return
    content_hashes.append(hash_value)
    state["dropbox_content_hashes"] = sorted(set(str(x) for x in content_hashes))
    _save_state(state)


