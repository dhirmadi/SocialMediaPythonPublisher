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


# --- #145 review follow-up: the files that actually run the gates -------------

CLAUDE_DIR = REPO_ROOT / ".claude"
CANONICAL_MYPY = "uv run mypy publisher_v2/src --ignore-missing-imports"

_MYPY_INVOCATION = re.compile(r"uv run mypy[^\n`]*")


# One list, used by every doc guard below: two lists drifted apart once already
# (the mypy guard did not cover the very files the dead-script finding was about).
_CONTRIBUTOR_DOCS = ("README.md", "AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", ".github/DEVELOPMENT.md", "Makefile")


def _repo_docs() -> list[Path]:
    """Every doc a contributor or subagent copies a gate command out of."""
    return [
        *(REPO_ROOT / name for name in _CONTRIBUTOR_DOCS),
        *sorted(CLAUDE_DIR.glob("agents/*.md")),
        *sorted(CLAUDE_DIR.glob("commands/*.md")),
    ]


def test_every_documented_mypy_invocation_is_the_working_one() -> None:
    """The broken `mypy .` form exits 2 on the duplicate conftest, wherever it lives."""
    offenders: dict[str, list[str]] = {}
    for path in _repo_docs():
        found = [m.group(0).strip().rstrip("`") for m in _MYPY_INVOCATION.finditer(path.read_text())]
        wrong = [command for command in found if command != CANONICAL_MYPY]
        if wrong:
            offenders[path.relative_to(REPO_ROOT).as_posix()] = wrong

    assert not offenders, f"these docs run a mypy command that exits 2: {offenders}"

    # Rejecting wrong forms is not enough: the guard must notice the command vanishing.
    for path in (AGENTS, CLAUDE, REPO_ROOT / "Makefile"):
        assert _MYPY_INVOCATION.search(path.read_text()), f"{path.name} no longer documents the type-check command"


def test_the_preview_command_does_not_pass_the_ignored_config_flag() -> None:
    """`--config` is accepted and ignored since #97 stage 4; the command must not teach it."""
    preview = (CLAUDE_DIR / "commands" / "preview.md").read_text()

    assert "--config" not in preview, preview
    assert ".ini" not in preview, preview


_RUN_PYTHON_SCRIPT = re.compile(r"uv run python\s+(?P<script>[\w./-]+\.py)")
_MAKE_TARGET = re.compile(r"^(?P<target>[a-zA-Z][\w-]*):", re.MULTILINE)
_ADVERTISED_TARGET = re.compile(r"make ([a-z][\w-]+)")


def test_makefile_targets_do_not_run_missing_scripts() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text()
    missing = sorted(
        {
            match.group("script")
            for match in _RUN_PYTHON_SCRIPT.finditer(makefile)
            if not (REPO_ROOT / match.group("script")).exists()
        }
    )

    assert not missing, f"Makefile recipes call scripts that do not exist: {missing}"


def test_makefile_only_advertises_targets_it_defines() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text()
    defined = {match.group("target") for match in _MAKE_TARGET.finditer(makefile)}
    advertised = {match.group(1) for match in _ADVERTISED_TARGET.finditer(makefile)}

    assert advertised <= defined, f"Makefile tells users to run undefined targets: {sorted(advertised - defined)}"


_V1_SCRIPT = re.compile(r"\bpy_[a-z_]+\.py\b")


def test_contributor_docs_do_not_reference_deleted_v1_scripts() -> None:
    """`py_db_auth.py` and `py_rotator_daily.py` were deleted with V1; no doc may still run them."""
    offenders: dict[str, list[str]] = {}
    for name in _CONTRIBUTOR_DOCS:
        path = REPO_ROOT / name
        dead = sorted({s for s in _V1_SCRIPT.findall(path.read_text()) if not (REPO_ROOT / s).exists()})
        if dead:
            offenders[name] = dead

    assert not offenders, f"docs reference scripts that no longer exist: {offenders}"
