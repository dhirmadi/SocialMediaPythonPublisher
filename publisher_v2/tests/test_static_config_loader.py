from __future__ import annotations

from pathlib import Path

from publisher_v2.config.static_loader import (
    StaticConfig,
    load_static_config,
    get_static_config,
)


def test_static_config_loads_packaged_defaults() -> None:
    cfg = get_static_config()
    assert isinstance(cfg, StaticConfig)
    # Basic sanity checks against known defaults
    assert cfg.platform_limits.instagram.max_caption_length == 2200
    assert cfg.platform_limits.instagram.max_hashtags == 30
    assert cfg.service_limits.ai.rate_per_minute == 20
    assert cfg.web_ui_text.values["title"] == "Publisher V2 Web"


def test_static_config_missing_dir_uses_defaults(tmp_path: Path, monkeypatch) -> None:
    # Point loader at an empty directory – should fall back to defaults.
    monkeypatch.setenv("PV2_STATIC_CONFIG_DIR", str(tmp_path))
    cfg = load_static_config(None)
    assert cfg.platform_limits.generic.max_caption_length == 2200
    assert cfg.service_limits.ai.rate_per_minute == 20


