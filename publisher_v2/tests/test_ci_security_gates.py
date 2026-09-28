"""PUB-055: the CI security gates must stay blocking, pinned and grouped.

The 2026-09-21 review checked these properties by hand once. These tests read
the real `.github` configuration so that re-adding `|| true`, a
`continue-on-error: true`, a mutable action ref or dropping Dependabot fails
here instead of quietly restoring the hole. No network, no subprocess: the
workflow files are read as text and parsed with `yaml.safe_load`.
"""

from __future__ import annotations

import re
import tomllib
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

    Handles both workflow files (`jobs.<job>.steps`) and composite actions
    (`runs.steps`, reported under the pseudo-job `<composite>`).
    """
    found: list[tuple[str, str]] = []
    for job_name, job in (document.get("jobs") or {}).items():
        if isinstance(job, dict) and isinstance(job.get("uses"), str):
            found.append((job_name, job["uses"]))
        for _job_name, step in _steps({"jobs": {job_name: job}}):
            if isinstance(step, dict) and isinstance(step.get("uses"), str):
                found.append((job_name, step["uses"]))
    runs = document.get("runs")
    if isinstance(runs, dict):
        for step in runs.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("uses"), str):
                found.append(("<composite>", step["uses"]))
    return found


# A repository-local action (`uses: ./.github/actions/<name>`) is resolved from
# the checked-out commit, so it is already pinned by that commit. What it runs
# inside is not — every `.github/actions/*/action.yml` is held to the same SHA
# rule below, so the exemption cannot smuggle a tag-pinned action into a
# security workflow.
_LOCAL_ACTION_REF = re.compile(r"^\./\.github/actions/[A-Za-z0-9._-]+/?$")


def _local_action_files() -> list[str]:
    return sorted(
        str(path.relative_to(REPO_ROOT))
        for pattern in ("action.yml", "action.yaml")
        for path in (REPO_ROOT / ".github/actions").glob(f"*/{pattern}")
    )


def _local_action_refs(relative_paths: list[str]) -> set[str]:
    return {
        ref.rstrip("/")
        for relative_path in relative_paths
        for _job, ref in _parsed_uses(_parse(relative_path))
        if ref.startswith("./")
    }


def test_every_action_in_the_security_workflows_is_pinned_by_sha() -> None:
    """AC4: every `uses:` is a 40-hex-char commit SHA with a version comment.

    Local `./.github/actions/<name>` refs are accepted (pinned by the checkout
    commit), and every local composite action is checked by the same rules.
    """
    action_files = _local_action_files()

    # Every local action referenced anywhere must resolve to an action file this
    # test checks; otherwise referencing one would silently escape the SHA rule.
    for ref in sorted(_local_action_refs(_workflow_paths() + action_files)):
        assert _LOCAL_ACTION_REF.match(ref), f"`{ref}` is not a `./.github/actions/<name>` local action ref"
        candidates = [f"{ref[2:]}/action.yml", f"{ref[2:]}/action.yaml"]
        assert any(candidate in action_files for candidate in candidates), (
            f"`{ref}` is referenced by a workflow but has no action.yml for the SHA-pin check to read"
        )

    for relative_path in [*SECURITY_WORKFLOWS, *action_files]:
        is_workflow = relative_path in SECURITY_WORKFLOWS
        lines = _read(relative_path).splitlines()
        pinned_count = 0

        # Parser-driven pass: catches refs a line regex cannot see.
        parsed = _parsed_uses(_parse(relative_path))
        if is_workflow:
            assert parsed, f"{relative_path}: no `uses:` found by the parser — this test would pass vacuously"
        for job_name, ref in parsed:
            if _LOCAL_ACTION_REF.match(ref):
                continue
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
            if _LOCAL_ACTION_REF.match(ref):
                continue
            assert _SHA_PINNED.match(ref), (
                f"{relative_path}:{index + 1} uses `{ref}`, not `<owner>/<repo>@<40-hex-char sha>`"
            )

            trailing = line.split(ref, 1)[1]
            following = lines[index + 1].strip() if index + 1 < len(lines) else ""
            comment = trailing if "#" in trailing else (following if following.startswith("#") else "")
            assert "#" in comment and re.search(r"\d", comment), (
                f"{relative_path}:{index + 1} pins `{ref}` without a version comment on the same or next line"
            )

        if is_workflow:
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


# --- PUB-084 wave 2b (#295): one ruff, one TruffleHog, one setup action, no no-op steps ---

PRECOMMIT_CONFIG = ".pre-commit-config.yaml"
SETUP_ACTION = ".github/actions/setup/action.yml"
LOCAL_SETUP_USES = "./.github/actions/setup"


def _workflow_paths() -> list[str]:
    paths = sorted(
        str(path.relative_to(REPO_ROOT))
        for pattern in ("*.yml", "*.yaml")
        for path in (REPO_ROOT / ".github/workflows").glob(pattern)
    )
    assert paths, "no workflow files found under .github/workflows — these tests would pass vacuously"
    return paths


def _jobs(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {name: job for name, job in (document.get("jobs") or {}).items() if isinstance(job, dict)}


def _job_steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in job.get("steps") or [] if isinstance(step, dict)]


def _step_label(step: dict[str, Any]) -> str:
    text = str(step.get("name") or step.get("uses") or step.get("run", "")).strip()
    return text.splitlines()[0] if text else "<empty step>"


def _triggers(document: dict[str, Any]) -> dict[str, Any]:
    """The workflow's `on:` block as a mapping.

    `yaml.safe_load` reads the bare key `on` as the boolean `True` (YAML 1.1),
    so both spellings are looked up. The string and list forms
    (`on: push`, `on: [push, pull_request]`) are normalised to a mapping.
    """
    raw = document.get("on", document.get(True))
    if isinstance(raw, str):
        return {raw: None}
    if isinstance(raw, list):
        return {str(event): None for event in raw}
    return dict(raw or {})


def _fires_on(document: dict[str, Any], event: str, branch: str = "main") -> bool:
    triggers = _triggers(document)
    if event not in triggers:
        return False
    config = triggers[event] or {}
    branches = config.get("branches") if isinstance(config, dict) else None
    return branches is None or branch in branches


def _job_runs_on(job: dict[str, Any], event: str) -> bool:
    """False only when the job's `if:` pins it to a different `github.event_name`."""
    condition = str(job.get("if", ""))
    pinned = re.findall(r"github\.event_name\s*==\s*['\"]([\w-]+)['\"]", condition)
    return not pinned or event in pinned


def _uses(step: dict[str, Any]) -> str:
    return str(step.get("uses") or "")


def test_precommit_ruff_uses_the_locked_version() -> None:
    """AC21: the pre-commit ruff hooks run the ruff pinned by uv.lock, not a separately pinned mirror."""
    document = _parse(PRECOMMIT_CONFIG)
    repos = [repo for repo in document.get("repos") or [] if isinstance(repo, dict)]

    mirrors = [str(repo.get("repo")) for repo in repos if "ruff-pre-commit" in str(repo.get("repo", ""))]
    assert not mirrors, (
        f"{PRECOMMIT_CONFIG} still pulls ruff from {mirrors} — its `rev:` pins a second ruff version "
        "that drifts from the one uv.lock gives local runs and CI"
    )

    for hook_id in ("ruff-format", "ruff"):
        found = [
            (repo.get("repo"), hook)
            for repo in repos
            for hook in repo.get("hooks") or []
            if isinstance(hook, dict) and hook.get("id") == hook_id
        ]
        assert found, f"{PRECOMMIT_CONFIG} has no `{hook_id}` hook"
        for repo_url, hook in found:
            assert repo_url == "local", (
                f"{PRECOMMIT_CONFIG}: the `{hook_id}` hook comes from `{repo_url}`, not a `repo: local` entry"
            )
            entry = str(hook.get("entry", "")).strip()
            assert re.match(r"^uv\s+run\s+(--\S+\s+)*ruff\b", entry), (
                f"{PRECOMMIT_CONFIG}: the local `{hook_id}` hook's entry is `{entry}`, not a `uv run ruff ...` command"
            )
            assert hook.get("language") == "system", (
                f"{PRECOMMIT_CONFIG}: the local `{hook_id}` hook must use `language: system` so it runs the "
                f"project's uv environment, not {hook.get('language')!r}"
            )


def test_trufflehog_runs_once_per_event() -> None:
    """AC22: a pull request and a push to main each get exactly one TruffleHog step."""
    for event in ("pull_request", "push"):
        steps: list[str] = []
        for relative_path in _workflow_paths():
            document = _parse(relative_path)
            if not _fires_on(document, event):
                continue
            for job_name, job in _jobs(document).items():
                if not _job_runs_on(job, event):
                    continue
                steps.extend(
                    f"{relative_path}::{job_name}::{_step_label(step)}"
                    for step in _job_steps(job)
                    if _uses(step).lower().startswith("trufflesecurity/trufflehog")
                )
        assert len(steps) == 1, f"`{event}` (to main) runs {len(steps)} TruffleHog steps, expected exactly one: {steps}"


SECRET_SCAN_WORKFLOW = ".github/workflows/secret-scan.yml"
_GHA_EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)
_SCHEDULE_EVENT_CHECK = re.compile(r"github\.event_name\s*==\s*['\"]schedule['\"]")


def test_secret_scan_runs_a_weekly_full_history_verified_scan() -> None:
    """PUB-084 wave 2b: secret-scan.yml keeps the weekly full-history verified TruffleHog scan.

    Folding security-scan.yml's TruffleHog step into secret-scan.yml must not drop the scheduled
    `--only-verified` sweep: the one step switches to verified mode on schedule/manual runs only.
    """
    document = _parse(SECRET_SCAN_WORKFLOW)
    triggers = _triggers(document)

    schedule = triggers.get("schedule")
    crons = [entry.get("cron") for entry in schedule or [] if isinstance(entry, dict) and entry.get("cron")]
    assert crons, f"{SECRET_SCAN_WORKFLOW} has no `schedule:` cron trigger — the weekly full-history scan is gone"
    assert "workflow_dispatch" in triggers, f"{SECRET_SCAN_WORKFLOW} cannot be run manually (no `workflow_dispatch:`)"

    located = [
        (job_name, index, steps)
        for job_name, job in _jobs(document).items()
        for steps in [_job_steps(job)]
        for index, step in enumerate(steps)
        if _uses(step).lower().startswith("trufflesecurity/trufflehog")
    ]
    assert len(located) == 1, f"{SECRET_SCAN_WORKFLOW} should have exactly one TruffleHog step, found {len(located)}"
    job_name, index, steps = located[0]
    trufflehog = steps[index]

    extra_args = str((trufflehog.get("with") or {}).get("extra_args") or "")
    expressions = _GHA_EXPRESSION.findall(extra_args)
    gated = [expr for expr in expressions if _SCHEDULE_EVENT_CHECK.search(expr) and "--only-verified" in expr]
    assert gated, (
        f"{SECRET_SCAN_WORKFLOW}::{job_name}: the TruffleHog step's `extra_args` ({extra_args!r}) does not derive "
        "`--only-verified` from an expression on `github.event_name == 'schedule'`"
    )
    unconditional = _GHA_EXPRESSION.sub("", extra_args)
    assert "--only-verified" not in unconditional, (
        f"{SECRET_SCAN_WORKFLOW}::{job_name}: `extra_args` ({extra_args!r}) passes `--only-verified` unconditionally, "
        "so pull_request/push runs would lose the default (unverified-included) mode"
    )

    checkouts = [step for step in steps[:index] if _uses(step).lower().startswith("actions/checkout")]
    assert checkouts, f"{SECRET_SCAN_WORKFLOW}::{job_name}: no checkout step before TruffleHog"
    fetch_depth = (checkouts[-1].get("with") or {}).get("fetch-depth")
    assert str(fetch_depth) == "0", (
        f"{SECRET_SCAN_WORKFLOW}::{job_name}: the checkout before TruffleHog has fetch-depth {fetch_depth!r}, "
        "not 0 — a scheduled scan would not see full history"
    )


def test_every_job_installs_through_the_shared_setup_action() -> None:
    """AC23: one composite action installs uv and the project; no job repeats that inline."""
    action = _parse(SETUP_ACTION)
    runs = action.get("runs") or {}
    assert runs.get("using") == "composite", f"{SETUP_ACTION} is not a composite action ({runs.get('using')!r})"
    action_steps = [step for step in runs.get("steps") or [] if isinstance(step, dict)]
    setup_uv = [step for step in action_steps if _uses(step).startswith("astral-sh/setup-uv")]
    assert setup_uv, f"{SETUP_ACTION} does not install uv with astral-sh/setup-uv"
    assert any(_is_truthy((step.get("with") or {}).get("enable-cache")) for step in setup_uv), (
        f"{SETUP_ACTION} installs uv without `enable-cache: true`"
    )
    assert any(re.search(r"\buv\s+sync\s+--group\s+dev\b", step.get("run") or "") for step in action_steps), (
        f"{SETUP_ACTION} never runs `uv sync --group dev`"
    )
    for step in action_steps:
        if "run" in step:
            assert step.get("shell"), f"{SETUP_ACTION}: composite `run` step `{_step_label(step)}` has no `shell:`"

    uses_local_action = 0
    problems: list[str] = []
    for relative_path in _workflow_paths():
        for job_name, job in _jobs(_parse(relative_path)).items():
            steps = _job_steps(job)
            where = f"{relative_path}::{job_name}"

            for step in steps:
                label = _step_label(step)
                if _uses(step).startswith("astral-sh/setup-uv"):
                    problems.append(f"{where}: inline setup-uv step `{label}`")
                if _uses(step).startswith("actions/setup-python"):
                    problems.append(f"{where}: separate setup-python step `{label}`")
                if re.search(r"\buv\s+sync\b", step.get("run") or ""):
                    problems.append(f"{where}: inline `uv sync` in step `{label}`")

            local = [index for index, step in enumerate(steps) if _uses(step).rstrip("/") == LOCAL_SETUP_USES]
            runs_uv = any(re.search(r"(?<![\w./-])uvx?\s", step.get("run") or "") for step in steps)
            if runs_uv and not local:
                problems.append(f"{where}: runs `uv` but never installs through `{LOCAL_SETUP_USES}`")
            if local:
                uses_local_action += 1
                checkouts = [index for index, step in enumerate(steps) if _uses(step).startswith("actions/checkout")]
                if not checkouts or min(checkouts) > local[0]:
                    problems.append(
                        f"{where}: uses `{LOCAL_SETUP_USES}` without an `actions/checkout` step before it — "
                        "a local action cannot be resolved until the repository is checked out"
                    )

    assert not problems, "jobs bypass the shared setup action:\n" + "\n".join(problems)
    assert uses_local_action, f"no workflow job uses `{LOCAL_SETUP_USES}` — this test would pass vacuously"


_INERT_LINE = re.compile(
    r"""^(?:
        (?:echo|printf)\b.*              # prints something
      | (?:then|else|fi|do|done|;;|esac) # bare shell control keywords
      | if\s+(?:\[|test\b).*;\s*then     # a test condition, not a command that can fail the step
      | .*\|\|\s*(?:echo|printf)\b.*     # a command whose failure is turned into a message
    )$""",
    re.VERBOSE,
)


def _is_noop_run(run: str) -> bool:
    """True when nothing in `run` can fail the step: only echoes, tests and echo-guarded commands."""
    lines = [line for line in _logical_lines(run) if not line.startswith("#")]
    if not lines:
        return True
    if any(re.search(r"\bexit\s+[1-9]", line) for line in lines):
        return False
    return all(_INERT_LINE.match(line) for line in lines)


def test_security_scan_has_no_noop_steps() -> None:
    """AC24: the committed-secrets check delegates to `make check-secrets`; no step only echoes."""
    relative_path = SECURITY_WORKFLOWS[0]
    steps = [step for _job, step in _steps(_parse(relative_path)) if isinstance(step, dict)]
    problems: list[str] = []

    delegating = [
        step
        for step in steps
        if any(re.fullmatch(r"make\s+check-secrets", line) for line in _logical_lines(step.get("run") or ""))
    ]
    if not delegating:
        problems.append("no step runs `make check-secrets` for the committed-secrets check")

    for step in steps:
        run = step.get("run")
        if not isinstance(run, str):
            continue
        label = _step_label(step)
        if "git ls-files" in run:
            problems.append(f"step `{label}` re-implements the `make check-secrets` pipeline inline")
        if _is_noop_run(run):
            problems.append(f"step `{label}` only echoes — it can never fail the build")

    assert not problems, f"{relative_path}:\n" + "\n".join(problems)


GITLEAKS_CONFIG = ".gitleaks.toml"

# Allowlist keys that would suppress findings by content, commit or rule
# rather than by the one baseline path.
_GITLEAKS_SUPPRESSING_KEYS = ("regexes", "stopwords", "commits", "rules", "targetRules")


def test_gitleaks_config_only_allowlists_the_detect_secrets_baseline() -> None:
    config = tomllib.loads(_read(GITLEAKS_CONFIG))

    assert (config.get("extend") or {}).get("useDefault") is True, (
        f"{GITLEAKS_CONFIG} must keep gitleaks' default rules via `[extend] useDefault = true`"
    )

    allowlists: list[dict[str, Any]] = []
    if "allowlist" in config:
        allowlists.append(config["allowlist"])
    allowlists.extend(config.get("allowlists") or [])
    for rule in config.get("rules") or []:
        if "allowlist" in rule:
            allowlists.append(rule["allowlist"])
        allowlists.extend(rule.get("allowlists") or [])

    paths = [path for allowlist in allowlists for path in allowlist.get("paths") or []]
    assert len(paths) == 1, f"expected exactly one allowlisted path, got {paths!r}"
    pattern = re.compile(paths[0])
    assert pattern.search(".secrets.baseline"), f"{paths[0]!r} does not match .secrets.baseline"
    for other in ("publisher_v2/tests/web/conftest.py", ".env", "secrets.baseline.bak", "x/.secrets.baseline"):
        assert not pattern.search(other), f"{paths[0]!r} also allowlists {other}"

    suppressing = [
        f"{key}={allowlist[key]!r}"
        for allowlist in allowlists
        for key in _GITLEAKS_SUPPRESSING_KEYS
        if key in allowlist
    ]
    assert not suppressing, f"{GITLEAKS_CONFIG} suppresses more than the baseline path: {suppressing}"


# PUB-085 #303: the gitleaks hook runs `gitleaks git --pre-commit --staged`, so on
# CI's fresh checkout (nothing staged) it scans nothing. CI must skip it openly
# and stop claiming it as a gate; SECURITY.md must say where it does run.
CODE_QUALITY_WORKFLOW = ".github/workflows/code-quality.yml"
SECURITY_DOC = "SECURITY.md"

# Other hooks/scanners a comment might enumerate alongside gitleaks as CI gates.
_OTHER_HOOK_NAMES = re.compile(r"detect-secrets|pydocstyle|bandit|ruff|mypy|trufflehog", re.IGNORECASE)
# Words that make a gitleaks sentence an explanation of the skip rather than a claim of enforcement.
_SKIP_EXPLANATION = re.compile(r"\bskip|\bstaged\b|\blocal", re.IGNORECASE)
# `SKIP=gitleaks uv run pre-commit ...`, `export SKIP="a,b"`, `SKIP='a'` inside a run script.
_INLINE_SKIP = re.compile(r"(?:^|[\s;&(])(?:export\s+)?SKIP=(?:\"([^\"]*)\"|'([^']*)'|(\S+))")


def _comment_blocks(text: str) -> list[list[str]]:
    """Contiguous runs of whole-line YAML comments (`#` stripped); each trailing comment is its own block."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            current.append(stripped.lstrip("#").strip())
            continue
        if current:
            blocks.append(current)
            current = []
        trailing = re.search(r"\s#\s(.*)$", line)
        if trailing:
            blocks.append([trailing.group(1).strip()])
    if current:
        blocks.append(current)
    return blocks


def _sentences(block: list[str]) -> list[str]:
    return [sentence for sentence in re.split(r"(?<=[.!?])\s+", " ".join(block)) if sentence]


def _skip_values(step: dict[str, Any], job: dict[str, Any], document: dict[str, Any]) -> list[str]:
    """Every SKIP the step's pre-commit invocation sees: step/job/workflow `env:` and inline assignments."""
    values: list[str] = []
    for scope in (step, job, document):
        env = scope.get("env")
        if isinstance(env, dict) and "SKIP" in env:
            values.append(str(env["SKIP"]))
    for match in _INLINE_SKIP.finditer(str(step.get("run") or "")):
        values.append(next(group for group in match.groups() if group is not None))
    return values


def _step_comment_text(text: str, step_name: str) -> str:
    """Comment lines directly above the named step plus every comment inside the step's own block."""
    lines = text.splitlines()
    header = re.compile(rf"^\s*-\s+name:\s*['\"]?{re.escape(step_name)}['\"]?\s*$")
    start = next((index for index, line in enumerate(lines) if header.match(line)), None)
    assert start is not None, f"could not find the `{step_name}` step in {CODE_QUALITY_WORKFLOW}"
    indent = len(lines[start]) - len(lines[start].lstrip())

    collected: list[str] = []
    above = start - 1
    while above >= 0 and lines[above].strip().startswith("#"):
        collected.insert(0, lines[above].strip())
        above -= 1

    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line.strip():
            current = len(line) - len(line.lstrip())
            if current < indent or (current == indent and line.lstrip().startswith("-")):
                break
        block.append(line)
    collected.extend(line[line.index("#") :].strip() for line in block if "#" in line)
    return " ".join(comment.lstrip("#").strip() for comment in collected)


def test_ci_precommit_job_skips_gitleaks_and_says_why() -> None:
    """AC1: CI's pre-commit step skips gitleaks explicitly, and no comment claims gitleaks as a CI gate."""
    text = _read(CODE_QUALITY_WORKFLOW)
    document = _parse(CODE_QUALITY_WORKFLOW)
    job = _jobs(document).get("pre-commit")
    assert job is not None, f"{CODE_QUALITY_WORKFLOW} has no `pre-commit` job"

    runners = [step for step in _job_steps(job) if re.search(r"\bpre-commit\s+run\b", str(step.get("run") or ""))]
    assert runners, f"the `pre-commit` job in {CODE_QUALITY_WORKFLOW} has no step running `pre-commit run`"

    for step in runners:
        label = _step_label(step)
        skip_values = _skip_values(step, job, document)
        skipped = {hook.strip() for value in skip_values for hook in value.split(",")}
        assert "gitleaks" in skipped, (
            f"step `{label}` runs pre-commit without SKIP containing gitleaks (SKIP values: {skip_values!r}); "
            "the hook scans only staged changes, so on CI's clean checkout it checks nothing"
        )

        # The step's existing detect-secrets note already says "locally, stage the
        # result", so the explanation must tie gitleaks to staged/local in one sentence.
        why = _step_comment_text(text, str(step.get("name")))
        assert any(
            re.search(r"gitleaks", sentence, re.IGNORECASE) and re.search(r"staged|local", sentence, re.IGNORECASE)
            for sentence in _sentences([why])
        ), (
            f"step `{label}` skips gitleaks without an adjacent comment explaining why "
            f"(expected a sentence naming gitleaks and 'staged' or 'local'); comment text: {why!r}"
        )

    # A sentence naming gitleaks is a claim of CI enforcement when it says the hook
    # runs "nowhere else", or lists it next to other gates without explaining the skip.
    claims = [
        sentence
        for block in _comment_blocks(text)
        for sentence in _sentences(block)
        if re.search(r"gitleaks", sentence, re.IGNORECASE)
        and (
            re.search(r"nowhere else", sentence, re.IGNORECASE)
            or (_OTHER_HOOK_NAMES.search(sentence) and not _SKIP_EXPLANATION.search(sentence))
        )
    ]
    assert not claims, f"{CODE_QUALITY_WORKFLOW} still has a comment listing gitleaks as a hook CI enforces: {claims}"


def _paragraphs(text: str) -> list[str]:
    return [" ".join(paragraph.split()) for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]


# `\blocal\b` or the literal `git commit` -- NOT a bare `commit`, which also matches inside "pre-commit".
_LOCAL_HOOK_WORDING = re.compile(r"\blocal\b|\bgit commit\b", re.IGNORECASE)
_CI_WORD = re.compile(r"\bCI\b")
_ENFORCEMENT_WORDING = re.compile(r"enforc|\bblock|\bgate", re.IGNORECASE)
# Only skip wording exempts a CI-enforcement sentence: "a local hook and a blocking CI gate" is still a CI claim.
_SKIP_WORDING = re.compile(r"\bskip", re.IGNORECASE)


def _gitleaks_doc_problems(text: str) -> list[str]:
    """Why the gitleaks sentences of `text` misdescribe the hook; empty when they are honest."""
    sentences = [
        sentence
        for paragraph in _paragraphs(text)
        for sentence in _sentences([paragraph])
        if re.search(r"gitleaks", sentence, re.IGNORECASE)
    ]
    if not sentences:
        return ["does not mention gitleaks at all"]
    problems = []
    if not any(_LOCAL_HOOK_WORDING.search(sentence) for sentence in sentences):
        problems.append(f"never describes gitleaks as a local hook that runs on `git commit`: {sentences}")
    for sentence in sentences:
        if _CI_WORD.search(sentence) and _ENFORCEMENT_WORDING.search(sentence) and not _SKIP_WORDING.search(sentence):
            problems.append(f"claims gitleaks is enforced in CI: {sentence!r}")
    return problems


def test_gitleaks_is_documented_as_a_local_hook() -> None:
    """AC2: the gitleaks hook stays configured; SECURITY.md says it is local and names the CI secret scanners."""
    config = _parse(PRECOMMIT_CONFIG)
    hook_ids = [
        hook.get("id")
        for repo in config.get("repos") or []
        if isinstance(repo, dict)
        for hook in repo.get("hooks") or []
        if isinstance(hook, dict)
    ]
    assert "gitleaks" in hook_ids, f"{PRECOMMIT_CONFIG} no longer configures the `gitleaks` hook"

    text = _read(SECURITY_DOC)
    problems = _gitleaks_doc_problems(text)
    assert not problems, f"{SECURITY_DOC}: " + "; ".join(problems)

    paragraphs = _paragraphs(text)

    whole = " ".join(paragraphs)
    for scanner in ("TruffleHog", "detect-secrets"):
        assert re.search(re.escape(scanner), whole, re.IGNORECASE), (
            f"{SECURITY_DOC} does not name {scanner}, one of the secret scanners that runs in CI"
        )
    assert any(
        re.search(r"\bCI\b|GitHub Actions|workflow", paragraph) and re.search(r"trufflehog", paragraph, re.IGNORECASE)
        for paragraph in paragraphs
    ), f"{SECURITY_DOC} names TruffleHog but never in a paragraph saying it runs in CI"
