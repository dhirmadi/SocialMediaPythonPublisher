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

# A non-blank line that cannot leave a paragraph open, so a 4-space-indented line
# directly after it does start an indented code block: an ATX heading, a thematic
# break, or an HTML block start.
NON_PARAGRAPH_LINE = re.compile(r"^ {0,3}(?:#{1,6}(?:\s|$)|(?:\*[ \t]*){3,}$|(?:-[ \t]*){3,}$|(?:_[ \t]*){3,}$|<)")


def _fence_opener(line: str) -> re.Match[str] | None:
    """The fence match for a line that may *open* a fenced block, else `None`.

    Per CommonMark a backtick fence's info string may not contain a backtick, so
    ```sh` is a paragraph rather than an opener. Accepting it would open a phantom
    fence whose next ``` "closes" it, inverting inside/outside for the rest of the
    file — exactly the masking class this matcher exists to kill.
    """
    match = CODE_FENCE.match(line)
    if match is None:
        return None
    if match.group("delimiter")[0] == "`" and "`" in match.group("info"):
        return None
    return match


def _code_lines(text: str) -> list[tuple[int, str]]:
    """1-indexed lines inside a code block, so prose or an inline `code span` is ignored.

    Covers all three CommonMark code-block forms, because an install instruction is
    just as real in any of them:

    * a ``` fence,
    * a ~~~ fence,
    * a 4-space / tab indented block.

    An indented code block cannot *interrupt a paragraph*, so it is recognised only
    where no paragraph is open: after a blank line, a heading, a thematic break, an
    HTML block start, or a closing fence. Paragraph state is tracked explicitly rather
    than approximated by "the previous line was blank", because the blank-line-only
    rule silently skipped every indented block that directly follows a heading.

    A fence is closed only by a fence of the *same* character that is at least as
    long and carries no info string, so a ``` line inside a ~~~ block (or a longer
    fence inside a shorter one) is content rather than a delimiter. The old
    implementation toggled a single boolean on every ``` line, which meant one
    unbalanced fence anywhere in a file silently inverted inside/outside for the rest
    of that file and could mask real hits below it.

    **Unclosed fence at EOF fails loud:** the trailing region stays classified as code
    and is still scanned. That is the safe direction — the alternative (treating it as
    prose) would let a malformed doc quietly opt out of the check.

    Known residual: a 4-space-indented list continuation paragraph is read as code.
    That fails in the loud direction (a false positive, never a silent skip) and
    separating the two cases needs a real Markdown parser.
    """
    lines: list[tuple[int, str]] = []
    fence_char: str | None = None
    fence_length = 0
    in_indented_block = False
    paragraph_open = False

    for number, line in enumerate(text.splitlines(), start=1):
        blank = not line.strip()

        if fence_char is not None:
            fence = CODE_FENCE.match(line)
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
            # Neither a fence delimiter nor its content leaves a paragraph open.
            paragraph_open = False
            continue

        opener = _fence_opener(line)
        if opener is not None:
            fence_char = opener.group("delimiter")[0]
            fence_length = len(opener.group("delimiter"))
            # A fence ends any indented block, so trailing lines are classified the
            # same way whether or not an unrelated indented block appeared earlier.
            in_indented_block = False
            paragraph_open = False
            continue

        indented = line.startswith("    ") or line.startswith("\t")
        if in_indented_block:
            # A blank line does not end an indented block; the next non-indented line does.
            if blank or indented:
                lines.append((number, line))
                continue
            in_indented_block = False
        elif indented and not paragraph_open:
            in_indented_block = True
            lines.append((number, line))
            continue

        paragraph_open = not blank and NON_PARAGRAPH_LINE.match(line) is None

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


# --- `_code_lines` classification, over literal fixtures rather than repo docs ------------
#
# No tracked doc contains a fenced install-from-a-missing-file line, so the AC2 test above
# can only ever fail on a *false positive*: a matcher that classifies too little (or
# nothing at all) still leaves it green. These fixtures pin the classification itself in
# both directions, so a regression that silently stops scanning code blocks fails here.


def _classified(lines: list[str]) -> list[tuple[int, str]]:
    """`_code_lines` over an explicit list of lines, so fixture indentation is literal."""
    return _code_lines("\n".join(lines))


def test_code_lines_ignores_prose_and_inline_code_spans() -> None:
    """A `code span` in a paragraph is prose, not a code block."""
    assert _classified(["Run `pip install -r requirements.txt` to start.", "", "More prose."]) == []


def test_code_lines_closes_a_fence_only_on_a_same_character_fence_of_at_least_its_length() -> None:
    """A shorter fence, or one of the other character, is content inside the open block."""
    assert _classified(["````", "```", "~~~", "````", "after"]) == [(2, "```"), (3, "~~~")]
    assert _classified(["~~~", "```sh", "pip install -r gone.txt", "```", "~~~", "after"]) == [
        (2, "```sh"),
        (3, "pip install -r gone.txt"),
        (4, "```"),
    ]


def test_code_lines_treats_a_closing_fence_carrying_an_info_string_as_content() -> None:
    """Only an info-string-free fence closes, so ``` python stays inside the block."""
    assert _classified(["```", "pip install -r gone.txt", "``` python", "still code", "```", "prose"]) == [
        (2, "pip install -r gone.txt"),
        (3, "``` python"),
        (4, "still code"),
    ]


def test_code_lines_ignores_a_backtick_fence_whose_info_string_holds_a_backtick() -> None:
    """Per CommonMark ```sh` is a paragraph; opening on it would invert the rest of the file."""
    lines = ["```sh`", "prose one", "```", "pip install -r gone.txt", "```", "tail prose"]
    assert _classified(lines) == [(4, "pip install -r gone.txt")]


def test_code_lines_reads_an_indented_block_after_a_blank_line() -> None:
    """Both a 4-space and a tab indent start a block, and a blank line inside does not end it."""
    for indent in ("    ", "\t"):
        lines = ["Intro.", "", f"{indent}pip install -r gone.txt", "", f"{indent}second command", "tail prose"]
        assert _classified(lines) == [
            (3, f"{indent}pip install -r gone.txt"),
            (4, ""),
            (5, f"{indent}second command"),
        ], indent


def test_code_lines_reads_an_indented_block_after_a_non_paragraph_line() -> None:
    """CommonMark only forbids interrupting a *paragraph*, so these indents are code."""
    for preceding in ("# Heading", "## Heading", "---", "***", "<div>"):
        lines = [preceding, "    pip install -r gone.txt", "tail prose"]
        assert _classified(lines) == [(2, "    pip install -r gone.txt")], preceding


def test_code_lines_does_not_read_an_indented_line_that_interrupts_a_paragraph() -> None:
    """An indented line inside an open paragraph is a lazy continuation, not a code block."""
    assert _classified(["Intro paragraph.", "    pip install -r gone.txt", "tail prose"]) == []


def test_code_lines_keeps_an_unclosed_fence_as_code_through_eof() -> None:
    """Fail loud: a malformed doc must not be able to opt its tail out of the scan."""
    assert _classified(["prose", "```sh", "pip install -r gone.txt", "more code"]) == [
        (3, "pip install -r gone.txt"),
        (4, "more code"),
    ]


def test_code_lines_distinguishes_a_three_space_fence_from_a_four_space_indented_block() -> None:
    """Up to 3 spaces is still a fence; 4 spaces is an indented block whose ``` is content."""
    assert _classified(["   ```", "pip install -r gone.txt", "   ```", "prose"]) == [(2, "pip install -r gone.txt")]
    assert _classified(["", "    ```", "    pip install -r gone.txt", "prose"]) == [
        (2, "    ```"),
        (3, "    pip install -r gone.txt"),
    ]


def test_code_lines_ends_an_indented_block_when_a_fence_opens() -> None:
    """Classification must not depend on an unrelated earlier indented block."""
    lines = ["Intro paragraph.", "", "    indented code", "```", "fenced code", "```", "", "tail prose"]
    assert _classified(lines) == [(3, "    indented code"), (5, "fenced code")]
