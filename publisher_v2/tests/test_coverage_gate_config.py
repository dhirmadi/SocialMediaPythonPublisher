"""#141: the coverage thresholds in CLAUDE.md must be enforced, not prose.

These read the real project configuration, so removing the gate (or pointing it
back at the whole repo, which inflates the figure with tests and tools) fails
here rather than silently in CI.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def test_coverage_measures_only_the_source_tree() -> None:
    run = _pyproject()["tool"]["coverage"]["run"]
    assert run["source"] == ["publisher_v2/src/publisher_v2"]


def test_the_threshold_survives_running_pytest_from_a_subdirectory() -> None:
    """coverage's own config lookup is cwd-relative; pytest's addopts is rootdir-relative."""
    addopts = _pyproject()["tool"]["pytest"]["ini_options"]["addopts"]
    assert "--cov-fail-under=85" in addopts


def test_coverage_report_fails_under_the_documented_threshold() -> None:
    report = _pyproject()["tool"]["coverage"]["report"]
    assert report["fail_under"] == 85
    assert report["show_missing"] is True
    assert report["skip_covered"] is False


def test_ci_runs_coverage_without_overriding_the_source_setting() -> None:
    workflow = (REPO_ROOT / ".github/workflows/code-quality.yml").read_text()
    assert "--cov=." not in workflow, "--cov=. measures tests and tools, inflating the figure"
    assert "--cov=" not in workflow, "an explicit --cov=<path> overrides [tool.coverage.run] source"
    # Finding 5: the gate can be neutralised without removing --cov at all.
    assert "--no-cov" not in workflow, "--no-cov disables the plugin and the threshold with it"
    assert "--cov-fail-under=0" not in workflow, "CI must not opt out of the threshold it exists to enforce"


def test_a_run_below_the_threshold_fails_end_to_end(tmp_path) -> None:
    """Wiring, not just presence: one trivial test covers almost nothing, so `--cov` must fail."""
    result = subprocess.run(  # noqa: S603 — fixed argv, no shell, no external input
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--cov",
            "--cov-report=term",
            "publisher_v2/tests/test_coverage_gate_config.py::test_coverage_measures_only_the_source_tree",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "COVERAGE_FILE": str(tmp_path / ".coverage"), "WEB_SESSION_SECRET": "x"},
    )

    assert result.returncode != 0, result.stdout[-2000:]
    assert "Coverage failure" in result.stdout, result.stdout[-2000:]


# --- #141 review follow-up ----------------------------------------------------


def test_the_ci_coverage_flag_is_matched_by_token_not_by_trailing_space() -> None:
    """`--cov\\n` would have slipped past a `"--cov "` substring check."""
    import re as _re

    workflow = (REPO_ROOT / ".github/workflows/code-quality.yml").read_text()

    assert _re.search(r"--cov(?=[\s\\])", workflow), "CI must still collect coverage"


def test_the_partial_run_escape_hatch_is_documented_where_contributors_look() -> None:
    """`--cov-fail-under=85` in addopts makes any partial `--cov` run fail.

    That is a deliberate trade for a gate that survives being run from a
    subdirectory, but it is a trap unless the way out is written down next to
    the commands people copy.
    """
    for name in ("CLAUDE.md", "AGENTS.md", "docs_v2/09_Reviews/QUALITY_METRICS.md"):
        text = (REPO_ROOT / name).read_text()
        assert "--cov-fail-under=0" in text, f"{name} does not document the partial-run escape hatch"


def test_disabling_the_coverage_plugin_is_documented_as_unsupported() -> None:
    """`pytest -p no:cov` errors on the unknown addopts argument; say so rather than let it surprise."""
    text = (REPO_ROOT / "AGENTS.md").read_text()

    index = text.find("-p no:cov")
    assert index != -1, "AGENTS.md should mention the coverage plugin cannot be disabled"
    # A doc saying "use -p no:cov to skip coverage" — the opposite of the truth —
    # would satisfy a bare substring check.
    assert "not supported" in text[max(0, index - 120) : index + 120], (
        "AGENTS.md mentions -p no:cov without saying it is unsupported"
    )


def test_a_single_file_coverage_run_is_available_as_a_make_target() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text()

    assert "test-cov-file:" in makefile, "no target for a partial coverage run"
    recipe = makefile.split("test-cov-file:", 1)[1].split("\n\n", 1)[0]
    assert "--cov-fail-under=0" in recipe, "the partial target must disable the total-run gate"
    # Finding 1: the target existing is not the same as it being discoverable.
    assert "test-cov-file" in makefile.split("help:", 1)[1].split("\n\n", 1)[0], "not listed in make help"
    assert "test-cov-file" in makefile.split(".PHONY:", 1)[1].splitlines()[0], "not in .PHONY"
