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
    assert "--cov " in workflow, "CI must still collect coverage"


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
