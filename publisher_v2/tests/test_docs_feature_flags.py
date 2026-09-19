"""#98 (HYG-3): every feature-flag env var documented in CONFIGURATION.md is parsed by the config layer.

Guards against phantom flags (documented but never read — see FEATURE_DELETE
pre-#97) and mismatched names (docs said FEATURE_AUTO_VIEW, loader read
AUTO_VIEW). The docs are scanned for flag-shaped env names; each must appear
in the config layer source, where all flag parsing lives.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs_v2" / "05_Configuration" / "CONFIGURATION.md"
CONFIG_SRC = REPO / "publisher_v2" / "src" / "publisher_v2" / "config"

FLAG_PATTERN = re.compile(r"\b(FEATURE_[A-Z_]+|AUTO_VIEW)\b")


def _documented_flags() -> set[str]:
    return set(FLAG_PATTERN.findall(DOCS.read_text(encoding="utf-8")))


def _config_layer_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in CONFIG_SRC.rglob("*.py"))


def test_all_documented_feature_flags_are_parsed_by_config_layer() -> None:
    documented = _documented_flags()
    assert documented, "No feature flags found in CONFIGURATION.md — pattern or doc moved?"
    source = _config_layer_source()
    phantom = sorted(flag for flag in documented if flag not in source)
    assert not phantom, f"Flags documented in CONFIGURATION.md but never parsed in config/: {phantom}"


def test_all_parsed_feature_flags_are_documented() -> None:
    """Reverse direction: a flag parsed in config/ must be documented."""
    parsed = set(FLAG_PATTERN.findall(_config_layer_source()))
    documented = _documented_flags()
    undocumented = sorted(parsed - documented)
    assert not undocumented, f"Flags parsed in config/ but missing from CONFIGURATION.md: {undocumented}"
