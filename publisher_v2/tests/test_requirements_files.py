"""PUB-066: a requirements file (or a doc) must not point at a requirements file that is gone.

`requirements-dev.txt:5` once referenced a `requirements.txt` removed during the uv migration, which broke
Dependabot's `pip`/`uv` updaters. Only tracked files are read, so a local `make export-reqs` output does not
fail the suite; the archived `code_v1/`/`docs_v1/` docs are never edited, so AC2 skips them.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ARCHIVED_TREES = ("code_v1/", "docs_v1/")

# pip accepts `-r file`, `-rfile`, `--requirement file` and `--requirement=file`; `#` after whitespace is a comment.
REQUIREMENT_FLAG = re.compile(r"(?:^|\s)(?:-r\s*|--requirement[\s=])(?P<target>[^\s#]+)")
# An install instruction, as opposed to a changelog mention or a `pip-audit -r <generated file>` invocation.
INSTALL_COMMAND = re.compile(r"\b(?:pip3?|python3?\s+-m\s+pip|uv\s+pip)\s+install\b")
# A ``` or ~~~ fenced code block; the closing fence repeats the opener's delimiter.
FENCED_BLOCK = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})[^\n]*\n(?P<code>.*?)^ {0,3}(?P=fence)\s*$", re.M | re.S)
REQUIREMENTS_NAME = re.compile(r"requirements[^/\s]*\.txt$")


def _tracked(pattern: str) -> list[Path]:
    """Tracked files matching a git pathspec that still exist in the worktree."""
    out = subprocess.run(  # noqa: S603 — fixed argv, no shell, no external input
        ["git", "ls-files", "-z", "--", pattern],  # noqa: S607 — git is expected on PATH in dev and CI
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [REPO_ROOT / rel for rel in out.split("\0") if rel and (REPO_ROOT / rel).is_file()]


def _install_targets(markdown: str) -> list[str]:
    """Requirements files that an install command inside a fenced code block installs from."""
    return [
        match.group("target")
        for block in FENCED_BLOCK.finditer(markdown)
        for line in block.group("code").splitlines()
        if INSTALL_COMMAND.search(line)
        for match in REQUIREMENT_FLAG.finditer(line)
        if REQUIREMENTS_NAME.search(match.group("target"))
    ]


def test_no_requirements_file_references_a_missing_target() -> None:
    """AC1: every `-r` / `--requirement` in a tracked requirements file must resolve (relative to that file)."""
    dangling = [
        f"{path.relative_to(REPO_ROOT)}:{number} references {match.group('target')!r}, which does not exist"
        for path in _tracked("*requirements*.txt")
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if not line.lstrip().startswith("#")
        for match in [REQUIREMENT_FLAG.search(" " + re.split(r"\s#", line, maxsplit=1)[0])]
        if match and not (path.parent / match.group("target")).exists()
    ]
    assert not dangling, "requirements files reference missing targets:\n" + "\n".join(dangling)


def test_the_docs_do_not_recommend_a_missing_requirements_file() -> None:
    """AC2: no fenced install instruction in a live Markdown doc names an absent requirements file.

    The self-check keeps this from passing vacuously if the fence regex stops matching anything.
    """
    sample = "Run `pip install -r prose.txt`.\n\n```sh\npip install -r requirements-gone.txt\n```\n"
    assert _install_targets(sample) == ["requirements-gone.txt"]

    stale = [
        f"{doc.relative_to(REPO_ROOT)} instructs installing from {target!r}, which does not exist"
        for doc in _tracked("*.md")
        if not str(doc.relative_to(REPO_ROOT)).startswith(ARCHIVED_TREES)
        for target in _install_targets(doc.read_text(encoding="utf-8"))
        if not (REPO_ROOT / target).exists()
    ]
    assert not stale, "docs recommend installing from missing requirements files:\n" + "\n".join(stale)
