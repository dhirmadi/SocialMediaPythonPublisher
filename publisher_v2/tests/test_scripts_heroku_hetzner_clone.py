import importlib.util
import pathlib
from types import ModuleType


def _load_script_module() -> ModuleType:
    root = pathlib.Path(__file__).resolve().parents[2]
    script_path = root / "scripts" / "heroku_hetzner_clone.py"
    spec = importlib.util.spec_from_file_location(
        "heroku_hetzner_clone", script_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Ensure the module is registered so dataclasses and other decorators
    # that inspect sys.modules can resolve it correctly.
    import sys as _sys

    _sys.modules[spec.name] = module  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_update_image_folder_updates_dropbox_section() -> None:
    module = _load_script_module()
    ini_text = """
[Dropbox]
image_folder = /Photos/old
archive = archive

[Other]
foo = bar
"""
    updated = module.update_image_folder(ini_text, "/Photos/new")  # type: ignore[attr-defined]

    assert "[Dropbox]" in updated
    assert "image_folder = /Photos/new" in updated
    assert "[Other]" in updated
    assert "foo = bar" in updated


def test_update_image_folder_raises_for_missing_section_or_key() -> None:
    module = _load_script_module()

    ini_missing_section = """
[Other]
foo = bar
"""
    ini_missing_key = """
[Dropbox]
archive = archive
"""

    for bad in (ini_missing_section, ini_missing_key):
        try:
            module.update_image_folder(bad, "/Photos/new")  # type: ignore[attr-defined]
        except ValueError:
            # Expected
            continue
        raise AssertionError("Expected ValueError for invalid FETLIFE_INI")


