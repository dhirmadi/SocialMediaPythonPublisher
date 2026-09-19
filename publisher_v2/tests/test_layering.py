"""#96: layering guard — services/ and core/ must not import from publisher_v2.web.

The web layer depends on services/core, never the reverse. One deliberate
exception exists as a backward-compat re-export shim and is allowlisted:

- services/tenant_factory.py — shim re-exporting TenantServiceFactory, which
  moved to publisher_v2/web/ (the reverse shim, web/sidecar_parser.py, imports
  in the allowed direction and needs no exemption)
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "publisher_v2"

# Compat shims that intentionally import from publisher_v2.web (re-exports only).
ALLOWLIST = {
    SRC / "services" / "tenant_factory.py",
}


def _web_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits.extend(a.name for a in node.names if a.name.startswith("publisher_v2.web"))
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("publisher_v2.web"):
            hits.append(node.module)
    return hits


def test_services_and_core_do_not_import_web() -> None:
    offenders: dict[str, list[str]] = {}
    for layer in ("services", "core", "utils", "config"):
        for path in sorted((SRC / layer).rglob("*.py")):
            if path in ALLOWLIST:
                continue
            hits = _web_imports(path)
            if hits:
                offenders[str(path.relative_to(SRC))] = hits
    assert not offenders, f"Lower layers import publisher_v2.web: {offenders}"


def test_allowlisted_shims_are_reexports_only() -> None:
    """Shims may only contain imports/assignments/docstrings — no logic."""
    for path in ALLOWLIST:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            assert isinstance(node, ast.Import | ast.ImportFrom | ast.Assign | ast.Expr), (
                f"{path.name} shim contains non-re-export code: {ast.dump(node)[:80]}"
            )
