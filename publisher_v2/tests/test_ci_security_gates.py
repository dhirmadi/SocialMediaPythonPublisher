"""PUB-055: the CI security gates must stay blocking, pinned and grouped.

The 2026-09-21 review checked these properties by hand once. These tests read
the real `.github` configuration so that re-adding `|| true`, a
`continue-on-error: true`, a mutable action ref or dropping Dependabot fails
here instead of quietly restoring the hole. No network, no subprocess: the
workflow files are read as text and parsed with `yaml.safe_load`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

# The two files PUB-055's Problem section is about. code-quality.yml and
# caption-eval-nightly.yml are explicitly out of scope for this item.
SECURITY_WORKFLOWS = (
    ".github/workflows/security-scan.yml",
    ".github/workflows/secret-scan.yml",
)

DEPENDABOT_CONFIG = ".github/dependabot.yml"

_USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)")
_SHA_PINNED = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+@[0-9a-f]{40}$")

# Every shell idiom that turns a non-zero exit into a green step: `|| true`,
# the unspaced `||true`, and the no-op builtin `|| :`.
_SWALLOWS_FAILURE = re.compile(r"\|\|\s*(?:true|:)(?![\w./=-])")


def _read(relative_path: str) -> str:
    path = REPO_ROOT / relative_path
    assert path.exists(), f"{relative_path} does not exist"
    return path.read_text()


def _parse(relative_path: str) -> dict[str, Any]:
    document = yaml.safe_load(_read(relative_path))
    assert isinstance(document, dict), f"{relative_path} did not parse to a mapping"
    return document


def _steps(document: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for job_name, job in (document.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            yield job_name, step


def _uncommented(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _is_truthy(value: Any) -> bool:
    """YAML `continue-on-error: true` and `continue-on-error: "true"` are the same bypass.

    `yaml.safe_load` gives the first a `bool` and the second a `str`, so an
    identity check against `True` silently misses the quoted form.

    A `${{ ... }}` expression is opaque to the parser but the runner evaluates it
    at run time, so `continue-on-error: ${{ true }}` or
    `continue-on-error: ${{ github.ref != 'refs/heads/main' }}` can bypass the
    gate on exactly the refs that matter. Any expression counts as truthy here:
    a blocking gate has no business being conditionally non-blocking.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if "${{" in value:
            return True
        return value.strip().lower() in {"true", "yes", "on", "1"}
    return value == 1


def test_no_security_step_swallows_a_failure() -> None:
    """AC3: nothing in either workflow turns a real finding into a green run."""
    for relative_path in SECURITY_WORKFLOWS:
        text = _read(relative_path)

        swallowed = _SWALLOWS_FAILURE.search(_uncommented(text))
        assert not swallowed, (
            f"{relative_path} swallows a command failure with `{swallowed.group(0) if swallowed else ''}`"
        )

        document = yaml.safe_load(text)
        for job_name, job in (document.get("jobs") or {}).items():
            assert not _is_truthy(job.get("continue-on-error")), (
                f"{relative_path}: job `{job_name}` is continue-on-error ({job.get('continue-on-error')!r})"
            )

        for job_name, step in _steps(document):
            label = step.get("name") or step.get("uses") or step.get("run", "")
            assert not _is_truthy(step.get("continue-on-error")), (
                f"{relative_path}: step `{label}` in job `{job_name}` is continue-on-error "
                f"({step.get('continue-on-error')!r})"
            )

            run = step.get("run") or ""
            assert not re.search(r"\bsafety\b", run), (
                f"{relative_path}: step `{label}` still invokes the removed `safety` scanner"
            )
            assert "safety" not in (step.get("uses") or ""), (
                f"{relative_path}: step `{label}` still uses a `safety` action"
            )

    # The GitGuardian presence guard is an `if:`, not a `continue-on-error:` —
    # it must survive the checks above rather than be removed to satisfy them.
    guarded = [
        step for _job, step in _steps(_parse(SECURITY_WORKFLOWS[0])) if "ggshield" in (step.get("uses") or "").lower()
    ]
    assert guarded, "the GitGuardian step disappeared from security-scan.yml"
    for step in guarded:
        assert "GITGUARDIAN_API_KEY" in str(step.get("if", "")), (
            "the GitGuardian step must be guarded on GITGUARDIAN_API_KEY being present, not run unconditionally"
        )


def _parsed_uses(document: dict[str, Any]) -> list[tuple[str, str]]:
    """Every `uses:` in the document, found by parsing rather than by line scanning.

    A flow-style step (`- {uses: 'actions/checkout@v4'}`) is invisible to a
    line-oriented regex but is a perfectly valid, perfectly unpinned action, so
    the authoritative list of refs comes from the parser.
    """
    found: list[tuple[str, str]] = []
    for job_name, job in (document.get("jobs") or {}).items():
        if isinstance(job, dict) and isinstance(job.get("uses"), str):
            found.append((job_name, job["uses"]))
        for _job_name, step in _steps({"jobs": {job_name: job}}):
            if isinstance(step, dict) and isinstance(step.get("uses"), str):
                found.append((job_name, step["uses"]))
    return found


def test_every_action_in_the_security_workflows_is_pinned_by_sha() -> None:
    """AC4: every `uses:` is a 40-hex-char commit SHA with a version comment."""
    for relative_path in SECURITY_WORKFLOWS:
        lines = _read(relative_path).splitlines()
        pinned_count = 0

        # Parser-driven pass: catches refs a line regex cannot see.
        parsed = _parsed_uses(_parse(relative_path))
        assert parsed, f"{relative_path}: no `uses:` found by the parser — this test would pass vacuously"
        for job_name, ref in parsed:
            assert _SHA_PINNED.match(ref), (
                f"{relative_path}: job `{job_name}` uses `{ref}`, not `<owner>/<repo>@<40-hex-char sha>`"
            )

        for index, line in enumerate(lines):
            if line.lstrip().startswith("#"):
                continue
            match = _USES_LINE.match(line)
            if not match:
                continue

            pinned_count += 1
            ref = match.group(1)
            assert _SHA_PINNED.match(ref), (
                f"{relative_path}:{index + 1} uses `{ref}`, not `<owner>/<repo>@<40-hex-char sha>`"
            )

            trailing = line.split(ref, 1)[1]
            following = lines[index + 1].strip() if index + 1 < len(lines) else ""
            comment = trailing if "#" in trailing else (following if following.startswith("#") else "")
            assert "#" in comment and re.search(r"\d", comment), (
                f"{relative_path}:{index + 1} pins `{ref}` without a version comment on the same or next line"
            )

        assert pinned_count, f"{relative_path}: no `uses:` step found — this test would pass vacuously"

        # The two passes must agree: a step written in flow style would be
        # checked for its SHA above but would never reach the comment check.
        assert pinned_count == len(parsed), (
            f"{relative_path}: the parser found {len(parsed)} `uses:` refs but the line scan found "
            f"{pinned_count} — a step is written in a form that escapes the version-comment check"
        )


def test_dependabot_config_groups_weekly_pip_and_actions_updates() -> None:
    """AC5: weekly, grouped minor/patch updates for both pip and github-actions."""
    document = _parse(DEPENDABOT_CONFIG)

    updates = document.get("updates") or []
    by_ecosystem = {entry.get("package-ecosystem"): entry for entry in updates}

    for ecosystem in ("pip", "github-actions"):
        assert ecosystem in by_ecosystem, f"{DEPENDABOT_CONFIG} does not declare the `{ecosystem}` ecosystem"
        entry = by_ecosystem[ecosystem]

        assert (entry.get("schedule") or {}).get("interval") == "weekly", (
            f"{DEPENDABOT_CONFIG}: `{ecosystem}` is not on a weekly schedule"
        )

        groups = entry.get("groups") or {}
        assert groups, f"{DEPENDABOT_CONFIG}: `{ecosystem}` has no `groups:` entry"
        update_types = {t for group in groups.values() for t in (group.get("update-types") or [])}
        assert {"minor", "patch"} <= update_types, (
            f"{DEPENDABOT_CONFIG}: `{ecosystem}` groups {sorted(update_types)}, not minor and patch"
        )

    # These apply to *every* declared ecosystem, including any added later (the
    # `uv` entry, for instance) — a neutered entry is as bad as a missing one.
    for entry in updates:
        ecosystem = entry.get("package-ecosystem")

        directories = entry.get("directories") or ([entry["directory"]] if entry.get("directory") else [])
        assert "/" in directories, (
            f"{DEPENDABOT_CONFIG}: `{ecosystem}` points at {directories!r}, not the repository root `/` — "
            "Dependabot silently finds no manifests there"
        )

        for ignored in entry.get("ignore") or []:
            name = str(ignored.get("dependency-name", ""))
            assert name not in {"*", ""}, (
                f"{DEPENDABOT_CONFIG}: `{ecosystem}` ignores `{name}` — that switches every update off"
            )
            ignored_types = set(ignored.get("versions") or []) | set(ignored.get("update-types") or [])
            assert not {"version-update:semver-minor", "version-update:semver-patch"} <= ignored_types, (
                f"{DEPENDABOT_CONFIG}: `{ecosystem}` ignores minor and patch updates for `{name}`, "
                "which is exactly what AC5 requires it to raise"
            )

        limit = entry.get("open-pull-requests-limit")
        assert limit is None or (isinstance(limit, int) and limit > 0), (
            f"{DEPENDABOT_CONFIG}: `{ecosystem}` has open-pull-requests-limit {limit!r} — "
            "0 disables version updates entirely"
        )


def _logical_lines(run: str) -> list[str]:
    """The `run:` body with backslash line continuations joined back together."""
    return [line.strip() for line in re.sub(r"\\\s*\n\s*", " ", run).splitlines() if line.strip()]


def _tokens(command: str) -> list[str]:
    return command.replace("'", " ").replace('"', " ").split()


def _option_value(tokens: list[str], *names: str) -> str | None:
    for index, token in enumerate(tokens):
        for name in names:
            if token == name and index + 1 < len(tokens):
                return tokens[index + 1]
            if token.startswith(f"{name}="):
                return token.split("=", 1)[1]
    return None


def test_the_pip_audit_step_blocks_on_the_project_dependencies() -> None:
    """AC3: the dependency gate exists, runs a pinned pip-audit over the real dependency set.

    The negative assertions elsewhere in this module only prove that nothing
    *says* `|| true`. They all survive deleting the pip-audit step outright, or
    pointing it at `/dev/null`. This is the positive half: the gate must be
    present, blocking, pinned, wired to the ignore script, and aimed at the
    project's actual dependencies.
    """
    relative_path = SECURITY_WORKFLOWS[0]
    document = _parse(relative_path)

    job = (document.get("jobs") or {}).get("security-scan")
    assert isinstance(job, dict), f"{relative_path}: the `security-scan` job is gone"

    invocation = re.compile(r"(?<![\w./-])pip-audit(?![\w./-])")
    audit_steps = [step for step in (job.get("steps") or []) if invocation.search(step.get("run") or "")]
    assert audit_steps, (
        f"{relative_path}: no step in the `security-scan` job runs `pip-audit` — "
        "the dependency-vulnerability gate has been removed"
    )

    for step in audit_steps:
        label = step.get("name") or "<unnamed pip-audit step>"
        run = step["run"]

        # The step has to actually execute and actually fail the job.
        assert not _is_truthy(step.get("continue-on-error")), f"{relative_path}: `{label}` is continue-on-error"
        condition = str(step.get("if", "")).strip().lower()
        assert condition.strip("${} ") not in {"false", "0"}, (
            f"{relative_path}: `{label}` is guarded by `if: {step.get('if')!r}` and never runs"
        )

        assert re.search(r"\bset\s+-[a-z]*e", run), (
            f"{relative_path}: `{label}` does not `set -e`, so a failing command mid-script is ignored"
        )
        assert not re.search(r"\bset\s+\+[a-z]*e", run), (
            f"{relative_path}: `{label}` re-enables error tolerance with `set +e`"
        )
        assert not re.search(r"(^|[;&\n|]\s*)exit\s+0\b", run), (
            f"{relative_path}: `{label}` ends in `exit 0`, which forces the step green"
        )

        # The tool itself must be version-pinned, whatever the runner
        # (`uvx --from`, `uv run --with`, `pip install`). The exact version is
        # deliberately not asserted — Dependabot is expected to bump it.
        assert re.search(r"pip-audit\s*==\s*\d+(\.\d+)+", run), (
            f"{relative_path}: `{label}` installs pip-audit without a `pip-audit==<x.y.z>` pin, "
            "so the scanner that decides pass/fail floats"
        )

        lines = _logical_lines(run)
        audit_lines = [line for line in lines if invocation.search(line) and "pip_audit_ignore" not in line]
        assert audit_lines, f"{relative_path}: `{label}` never invokes pip-audit on its own line"

        # The ignore list must be computed by the reviewed script and actually
        # handed to pip-audit, not merely mentioned.
        assert "scripts/pip_audit_ignore.py" in run, (
            f"{relative_path}: `{label}` does not wire in `scripts/pip_audit_ignore.py`"
        )
        assignment = re.search(r"([A-Za-z_][A-Za-z0-9_]*)=[^\n]*pip_audit_ignore\.py", run)
        if assignment:
            variable = assignment.group(1)
            assert any(f"${variable}" in line or f"${{{variable}}}" in line for line in audit_lines), (
                f"{relative_path}: `{label}` computes `{variable}` from the ignore script but never passes it "
                "to pip-audit"
            )

        for audit_line in audit_lines:
            tokens = _tokens(audit_line)
            target = _option_value(tokens, "-r", "--requirement")

            if target is None:
                # Auditing the live environment is fine, but only if pip-audit
                # is allowed to resolve it.
                assert "--no-deps" not in tokens, (
                    f"{relative_path}: `{label}` runs pip-audit with `--no-deps` and no requirements file, "
                    "so it audits nothing"
                )
                continue

            assert target not in {"/dev/null", "-"} and not target.startswith("/dev/"), (
                f"{relative_path}: `{label}` audits `{target}` — an empty target always passes"
            )

            generator = next(
                (
                    line
                    for line in lines
                    if line is not audit_line and target in line and invocation.search(line) is None
                ),
                None,
            )
            checked_in = (REPO_ROOT / target).exists()
            assert generator is not None or checked_in, (
                f"{relative_path}: `{label}` audits `{target}`, which is neither checked into the repository "
                "nor generated earlier in the same step — pip-audit would see an absent or empty file"
            )
            if generator is not None:
                assert re.search(r"\buv\s+(export|pip\s+(compile|freeze))\b|\bpip\s+freeze\b", generator), (
                    f"{relative_path}: `{label}` builds `{target}` with `{generator}`, which is not an export "
                    "of the project's dependency set"
                )
                assert "--no-deps" not in _tokens(generator), (
                    f"{relative_path}: `{label}` exports `{target}` with `--no-deps`, so transitive "
                    "dependencies are never audited"
                )
