"""#96: layering guard — services/ and core/ must not import from publisher_v2.web.

The web layer depends on services/core, never the reverse. #144 removed the
last exception — services/tenant_factory.py, a re-export shim with no
importers — so the allowlist is now empty. (The reverse shim,
web/sidecar_parser.py, imports in the allowed direction and needs no
exemption.)
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "publisher_v2"

# Compat shims that intentionally import from publisher_v2.web (re-exports only).
# Empty since #144: add an entry only with a documented reason and a removal plan.
ALLOWLIST: set[Path] = set()


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


# --- #142: no reaching into storage privates from web/ or tools/ ---

# Locals/attributes that hold a storage object in these layers. The match is by
# NAME, so an unrelated `self.target._retries` in web/ or tools/ would also be
# flagged; allowlist it here if that ever happens rather than widening the rule.
_STORAGE_NAMES = {"storage", "source", "target"}
_STORAGE_BASES = {"ManagedStorage", "DropboxStorage", "StorageProtocol", "ObjectStorageProtocol"}


def _private_storage_access(path: Path) -> list[str]:
    """Reads like ``storage._bucket`` / ``target.client``, or a storage subclass at all.

    Subclassing a backend is the same break seen from the inside: the subclass
    then reaches ``self.client``/``self._bucket`` and can shadow a protocol
    method with an unmetered version (#142).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                if name in _STORAGE_BASES:
                    hits.append(f"class {node.name}({name})")
            continue
        if not isinstance(node, ast.Attribute):
            continue
        base = node.value
        # Both ``storage._bucket`` and the chained ``self.storage._bucket`` /
        # ``service.storage.client`` — the latter is how web/ holds storage.
        if isinstance(base, ast.Name):
            owner = base.id
        elif isinstance(base, ast.Attribute):
            owner = base.attr
        else:
            continue
        if owner not in _STORAGE_NAMES:
            continue
        if node.attr == "client" or (node.attr.startswith("_") and not node.attr.startswith("__")):
            hits.append(f"{owner}.{node.attr}")
    return hits


def test_web_and_tools_use_the_storage_protocol_only() -> None:
    offenders: dict[str, list[str]] = {}
    for layer in ("web", "tools"):
        for path in sorted((SRC / layer).rglob("*.py")):
            hits = _private_storage_access(path)
            if hits:
                offenders[str(path.relative_to(SRC))] = hits
    assert offenders == {}, f"storage internals reached outside services/: {offenders}"
