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


# An opening/closing code fence: up to 3 leading spaces, then 3+ backticks or 3+ tildes.
# More than 3 spaces of indent makes it an indented code block instead, never a fence.
CODE_FENCE = re.compile(r"^ {0,3}(?P<delimiter>`{3,}|~{3,})(?P<info>.*)$")


def _code_lines(text: str) -> list[tuple[int, str]]:
    """1-indexed lines inside a code block, so prose or an inline `code span` is ignored.

    Covers all three CommonMark code-block forms, because an install instruction is
    just as real in any of them:

    * a ``` fence,
    * a ~~~ fence,
    * a 4-space / tab indented block (which, per CommonMark, cannot interrupt a
      paragraph, so it must be preceded by a blank line).

    A fence is closed only by a fence of the *same* character that is at least as
    long and carries no info string, so a ``` line inside a ~~~ block (or a longer
    fence inside a shorter one) is content rather than a delimiter. The old
    implementation toggled a single boolean on every ``` line, which meant one
    unbalanced fence anywhere in a file silently inverted inside/outside for the rest
    of that file and could mask real hits below it.

    **Unclosed fence at EOF fails loud:** the trailing region stays classified as code
    and is still scanned. That is the safe direction — the alternative (treating it as
    prose) would let a malformed doc quietly opt out of the check.
    """
    lines: list[tuple[int, str]] = []
    fence_char: str | None = None
    fence_length = 0
    in_indented_block = False
    after_blank = True

    for number, line in enumerate(text.splitlines(), start=1):
        blank = not line.strip()
        fence = CODE_FENCE.match(line)

        if fence_char is not None:
            delimiter = fence.group("delimiter") if fence else ""
            closes = (
                fence is not None
                and delimiter[0] == fence_char
                and len(delimiter) >= fence_length
                and not fence.group("info").strip()
            )
            if closes:
                fence_char = None
            else:
                lines.append((number, line))
            after_blank = False
            continue

        if fence is not None:
            fence_char = fence.group("delimiter")[0]
            fence_length = len(fence.group("delimiter"))
            after_blank = False
            continue

        indented = line.startswith("    ") or line.startswith("\t")
        if in_indented_block:
            # A blank line does not end an indented block; the next non-indented line does.
            if blank or indented:
                lines.append((number, line))
                after_blank = blank
                continue
            in_indented_block = False
        elif indented and after_blank:
            in_indented_block = True
            lines.append((number, line))
            after_blank = False
            continue

        after_blank = blank

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
        for number, line in _code_lines(text):
            if not INSTALL_COMMAND.search(line):
                continue
            for match in REQUIREMENT_FLAG.finditer(line):
                target = match.group("target")
                if not _is_requirements_name(target):
                    continue
                if not (REPO_ROOT / target).exists():
                    stale.append(f"{relative}:{number} instructs installing from {target!r}, which does not exist")

    assert not stale, "docs recommend installing from missing requirements files:\n" + "\n".join(stale)
