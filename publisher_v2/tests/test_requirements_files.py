"""PUB-066: a requirements file (or a doc) must not point at a requirements file that is gone.

`requirements-dev.txt:5` referenced a `requirements.txt` removed during the uv
migration, which is the suspected cause of Dependabot's `pip`/`uv` updaters
aborting with `/requirements.txt not found`. These tests assert the repository
hygiene that makes that state impossible to reintroduce; they do not, and
cannot, assert that Dependabot recovered (that is AC3, a live verification).

Only tracked files are considered, so a local `make export-reqs` output does not
fail the suite. The archived `code_v1/` and `docs_v1/` trees are read for AC1
(they are real requirements files) but excluded from AC2, which asserts the
install instructions contributors actually follow — archived docs are never
edited.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

ARCHIVED_TREES = ("code_v1/", "docs_v1/")

# pip accepts `-r file`, `-rfile`, `--requirement file` and `--requirement=file`.
REQUIREMENT_FLAG = re.compile(r"(?:^|\s)(?:-r\s*|--requirement[\s=])(?P<target>[^\s#]+)")

# An install instruction, as opposed to a mention of the filename in a changelog
# entry or a `pip-audit -r <generated file>` invocation.
INSTALL_COMMAND = re.compile(r"\b(?:pip3?|python3?\s+-m\s+pip|uv\s+pip)\s+install\b")


def _tracked(pattern: str) -> list[str]:
    """Tracked paths matching a git pathspec, as repo-root-relative POSIX strings."""
    completed = subprocess.run(  # noqa: S603 — fixed argv, no shell, no external input
        ["git", "ls-files", "-z", "--", pattern],  # noqa: S607 — git is expected on PATH in dev and CI
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [path for path in completed.stdout.split("\0") if path]


def _is_requirements_name(target: str) -> bool:
    """Match the git pathspec used above: `requirements` anywhere in a `.txt` name."""
    return fnmatch.fnmatch(Path(target).name, "*requirements*.txt")


def _strip_inline_comment(line: str) -> str:
    """pip treats `#` as a comment when it starts a line or follows whitespace."""
    if line.lstrip().startswith("#"):
        return ""
    return re.split(r"\s#", line, maxsplit=1)[0]


def _fenced_code_lines(text: str) -> list[tuple[int, str]]:
    """1-indexed lines inside ``` fences, so prose mentioning a command is ignored."""
    lines: list[tuple[int, str]] = []
    inside = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            inside = not inside
            continue
        if inside:
            lines.append((number, line))
    return lines


def test_no_requirements_file_references_a_missing_target() -> None:
    """AC1: every `-r` / `--requirement` in a tracked requirements file must resolve."""
    dangling: list[str] = []

    for relative in _tracked("*requirements*.txt"):
        path = REPO_ROOT / relative
        # A tracked file deleted from the worktree cannot hold a dangling reference.
        if not _is_requirements_name(path.name) or not path.is_file():
            continue
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = REQUIREMENT_FLAG.search(f" {_strip_inline_comment(raw)}")
            if match is None:
                continue
            target = match.group("target")
            # pip resolves a nested requirement relative to the referencing file.
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                # `-r ../outside.txt` resolves out of the tree, where relative_to() raises.
                try:
                    shown = resolved.relative_to(REPO_ROOT).as_posix()
                except ValueError:
                    shown = str(resolved)
                dangling.append(
                    f"{relative}:{number} references {target!r}, which does not exist (resolved to {shown})"
                )

    assert not dangling, "requirements files reference missing targets:\n" + "\n".join(dangling)


def test_the_docs_do_not_recommend_a_missing_requirements_file() -> None:
    """AC2: no live Markdown doc tells a contributor to install from an absent requirements file."""
    stale: list[str] = []

    for relative in _tracked("*.md"):
        if relative.startswith(ARCHIVED_TREES):
            continue
        doc = REPO_ROOT / relative
        if not doc.is_file():
            continue
        text = doc.read_text(encoding="utf-8")
        for number, line in _fenced_code_lines(text):
            if not INSTALL_COMMAND.search(line):
                continue
            for match in REQUIREMENT_FLAG.finditer(line):
                target = match.group("target")
                if not _is_requirements_name(target):
                    continue
                if not (REPO_ROOT / target).exists():
                    stale.append(f"{relative}:{number} instructs installing from {target!r}, which does not exist")

    assert not stale, "docs recommend installing from missing requirements files:\n" + "\n".join(stale)
