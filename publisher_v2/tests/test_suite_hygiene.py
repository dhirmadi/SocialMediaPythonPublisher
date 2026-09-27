"""Suite-wide hygiene guards (PUB-084).

These tests check properties of the test suite itself: that the autouse setup isolates
process-wide state for every test, and that per-file copies of that isolation do not creep back.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from publisher_v2.utils import state

TESTS_ROOT = Path(__file__).resolve().parent
THIS_FILE = Path(__file__).resolve()

_XDG_SETTERS = re.compile(
    r"""setenv\(\s*["']XDG_CACHE_HOME["']"""
    r"""|setitem\(\s*os\.environ\s*,\s*["']XDG_CACHE_HOME["']"""
    r"""|os\.environ\[\s*["']XDG_CACHE_HOME["']\s*\]\s*="""
    r"""|["']XDG_CACHE_HOME["']\s*:"""
)
_BYPASS_DEDUP = re.compile(r"\bbypass_dedup\b")
# Isolation-only no-op patches of the posted-state helpers, e.g.
#   monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
#   monkeypatch.setattr("publisher_v2.core.workflow.save_posted_hash", lambda h: None)
# Behavioural patches (non-empty sets, recorders such as ``lambda v: saved.append(v)``) are allowed.
_NOOP_POSTED_STATE_PATCH = re.compile(
    r"""setattr\(\s*[^()]*?\b(?:load|save)_posted_\w+["']?\s*,\s*lambda[^:()]*:\s*(?:set\(\s*\)|None)\s*,?\s*\)"""
)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


@pytest.mark.parametrize("run", ["first", "second"])
def test_posted_state_cache_is_isolated_per_test(tmp_path_factory: pytest.TempPathFactory, run: str) -> None:
    """AC1: autouse setup points XDG_CACHE_HOME at a per-test temp dir; utils.state resolves there.

    Runs twice and records a posted hash each time: if the dir were shared (session-scoped),
    whichever run goes second would find the other's posted.json instead of an empty dir.
    """
    xdg = os.environ.get("XDG_CACHE_HOME")
    assert xdg, "autouse test setup must set XDG_CACHE_HOME for every test"
    assert Path(xdg).name.startswith("xdg-cache"), f"XDG_CACHE_HOME={xdg!r} is not the autouse per-test dir"
    assert list(Path(xdg).iterdir()) == [], f"XDG_CACHE_HOME={xdg!r} is not empty at test start ({run} run)"
    assert state.load_posted_hashes() == set()

    basetemp = tmp_path_factory.getbasetemp()
    home = Path.home()
    assert _is_within(Path(xdg), basetemp), f"XDG_CACHE_HOME={xdg!r} is not inside pytest's temp dir {basetemp}"
    assert not _is_within(Path(xdg), home / ".cache"), f"XDG_CACHE_HOME={xdg!r} points at the real ~/.cache"

    cache = state._cache_path()
    assert _is_within(cache, Path(xdg)), f"posted-state cache {cache} does not resolve under {xdg}"
    assert not _is_within(cache, home / ".cache"), f"posted-state cache {cache} resolves under the real home"

    state.save_posted_hash(f"hygiene-{run}")
    assert state.load_posted_hashes() == {f"hygiene-{run}"}


def test_no_per_file_posted_state_isolation() -> None:
    """AC2: no per-file XDG_CACHE_HOME, bypass_dedup fixture, or no-op posted-state patch exists."""
    xdg_offenders: list[str] = []
    bypass_offenders: list[str] = []
    noop_patch_offenders: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        if path.resolve() == THIS_FILE:
            continue
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(TESTS_ROOT))
        if path.name != "conftest.py":
            for lineno, line in enumerate(text.splitlines(), start=1):
                if _XDG_SETTERS.search(line):
                    xdg_offenders.append(f"{rel}:{lineno}")
        if _BYPASS_DEDUP.search(text):
            bypass_offenders.append(rel)
        for match in _NOOP_POSTED_STATE_PATCH.finditer(text):
            lineno = text.count("\n", 0, match.start()) + 1
            noop_patch_offenders.append(f"{rel}:{lineno}")

    assert not xdg_offenders, (
        "per-file XDG_CACHE_HOME isolation is redundant with the autouse setup; remove it from: "
        + ", ".join(xdg_offenders)
    )
    assert not bypass_offenders, "bypass_dedup must not be defined or used; found in: " + ", ".join(bypass_offenders)
    assert not noop_patch_offenders, (
        "no-op load_posted_*/save_posted_* patches are redundant with the autouse per-test XDG cache; "
        "remove them from: " + ", ".join(noop_patch_offenders)
    )
