"""#145: AGENTS.md and CLAUDE.md must document the same, working commands.

AGENTS.md carried `uv run mypy . --ignore-missing-imports --exclude=venv
--exclude=env`, which exits 2 on the duplicate conftest; CLAUDE.md had already
moved to `mypy publisher_v2/src`. Anyone following the shared standard hit an
error that looked like a broken type checker.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS = REPO_ROOT / "AGENTS.md"
CLAUDE = REPO_ROOT / "CLAUDE.md"

_GATE_ROW = re.compile(r"^\|\s*(?P<gate>[^|]+?)\s*\|\s*`(?P<command>[^`]+)`\s*\|", re.MULTILINE)


def _gate_commands(path: Path) -> dict[str, list[str]]:
    """Every command documented per gate name — AGENTS.md lists some twice.

    Keyed on the gate name with ALL matches kept: a dict of single values would
    silently compare only the last row, leaving the quick-reference table free
    to drift (which is exactly the defect #145 is about).
    """
    commands: dict[str, list[str]] = {}
    for match in _GATE_ROW.finditer(path.read_text()):
        gate = match.group("gate").strip().lower()
        # AGENTS.md's quick reference says "Test", its gate table says "Tests".
        gate = {"test": "tests", "test + coverage": "coverage"}.get(gate, gate)
        commands.setdefault(gate, []).append(match.group("command").strip())
    return commands


def test_type_check_command_is_identical_everywhere_it_appears() -> None:
    agents, claude = _gate_commands(AGENTS), _gate_commands(CLAUDE)

    # AGENTS.md documents it twice: quick reference and quality gates.
    assert len(agents["type check"]) >= 2, agents["type check"]
    documented = set(agents["type check"]) | set(claude["type check"])
    assert len(documented) == 1, f"the mypy command differs between/within the files: {sorted(documented)}"


def test_test_command_is_identical_everywhere_it_appears() -> None:
    agents, claude = _gate_commands(AGENTS), _gate_commands(CLAUDE)

    assert len(agents["tests"]) >= 2, agents["tests"]
    documented = set(agents["tests"]) | set(claude["tests"])
    assert len(documented) == 1, f"the pytest command differs between/within the files: {sorted(documented)}"


def test_the_documented_type_check_command_exits_zero() -> None:
    command = _gate_commands(CLAUDE)["type check"][0]
    assert command.startswith("uv run mypy"), command

    # "uv run mypy ..." runs as "python -m mypy ..." here: under `uv run pytest`
    # that is the same interpreter and the same mypy the documented command uses.
    result = subprocess.run(  # noqa: S603 — fixed argv built from the repo's own docs
        [sys.executable, "-m", *command.removeprefix("uv run ").split()],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
