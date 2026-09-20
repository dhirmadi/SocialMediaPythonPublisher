from __future__ import annotations

from pathlib import Path

from publisher_v2.config.static_loader import (
    StaticConfig,
    get_static_config,
    load_static_config,
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


def test_packaged_static_yaml_has_no_duplicate_keys() -> None:
    """A duplicate mapping key is silently resolved to the last one by PyYAML.

    ``web_ui_text.en.yaml`` defined ``placeholders`` twice; the first block was
    dropped on load, and nothing noticed because the surviving block happened to
    be a superset. A stricter loader would have rejected the file outright, and a
    future edit to the wrong block would vanish with no error.
    """
    import yaml

    static_dir = Path(__file__).resolve().parents[1] / "src" / "publisher_v2" / "config" / "static"
    yaml_files = sorted(static_dir.glob("*.yaml"))
    assert yaml_files, f"no packaged static YAML found in {static_dir}"

    class _DuplicateKeyGuard(yaml.SafeLoader):
        pass

    def _no_duplicates(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
        seen: set = set()
        for key_node, _ in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in seen:
                raise AssertionError(f"duplicate key {key!r} at line {key_node.start_mark.line + 1}")
            seen.add(key)
        return loader.construct_mapping(node, deep=deep)

    _DuplicateKeyGuard.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates)

    for path in yaml_files:
        with path.open(encoding="utf-8") as handle:
            yaml.load(handle, Loader=_DuplicateKeyGuard)  # noqa: S506 — guarded SafeLoader subclass
