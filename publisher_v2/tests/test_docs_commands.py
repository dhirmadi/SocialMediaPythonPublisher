"""#145: AGENTS.md and CLAUDE.md must document the same, working commands.

AGENTS.md carried `uv run mypy . --ignore-missing-imports --exclude=venv
--exclude=env`, which exits 2 on the duplicate conftest; CLAUDE.md had already
moved to `mypy publisher_v2/src`. Anyone following the shared standard hit an
error that looked like a broken type checker.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

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


EXPECTED_GATES = {"format", "lint", "type check", "tests", "coverage"}


def test_every_expected_gate_row_is_still_matched() -> None:
    """_GATE_ROW keys on the first column; a renamed row would silently stop being compared."""
    for path in (AGENTS, CLAUDE):
        missing = sorted(EXPECTED_GATES - _gate_commands(path).keys())
        assert not missing, f"{path.name} no longer has a parseable row for: {missing}"


@pytest.mark.parametrize(("gate", "tool"), [("type check", "mypy"), ("tests", "pytest")])
def test_command_is_identical_everywhere_it_appears(gate: str, tool: str) -> None:
    agents, claude = _gate_commands(AGENTS), _gate_commands(CLAUDE)

    # AGENTS.md documents each twice: quick reference and quality gates.
    assert len(agents[gate]) >= 2, agents[gate]
    documented = set(agents[gate]) | set(claude[gate])
    assert len(documented) == 1, f"the {tool} command differs between/within the files: {sorted(documented)}"


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("RUN_SLOW_DOC_CHECKS") != "1",
    reason="full mypy pass; CI runs the same command as its own job. Set RUN_SLOW_DOC_CHECKS=1 to run it here.",
)
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


def test_readme_does_not_teach_the_removed_ini_configuration() -> None:
    """#97 stage 4 removed INI parsing; README's config section must not show an INI file."""
    readme = (REPO_ROOT / "README.md").read_text()

    assert "```ini" not in readme, "README still carries an INI configuration example"
    assert "[openAI]" not in readme, "README still documents INI sections"


_ENV_ASSIGNMENT = re.compile(r"^(?P<key>[A-Z][A-Z0-9_]*)=(?P<value>.*)$")
_H2 = re.compile(r"^## .*$", re.MULTILINE)
_CONFIG_HEADING = re.compile(r"^## [^\n]*\bConfiguration\b[^\n]*$", re.MULTILINE)


def _readme_env_example() -> tuple[dict[str, str], dict[str, str]]:
    """The `.env` example README teaches under its "## ... Configuration" heading.

    Returns ``(secrets, dynamic_config)``: KEY=VALUE lines below the ``# Secrets``
    comment and below the ``# Dynamic config`` comment of the first ```bash block
    in that section. Matched on the heading text so decoration (emoji) can change.
    """
    readme = (REPO_ROOT / "README.md").read_text()
    heading = _CONFIG_HEADING.search(readme)
    if heading is None:
        pytest.fail("README has no '## ... Configuration' section; the env-example checks cannot run")
    next_heading = _H2.search(readme, heading.end())
    section = readme[heading.end() : next_heading.start() if next_heading else len(readme)]

    fence = section.find("```bash")
    if fence == -1:
        pytest.fail("README Configuration section has no ```bash .env example")
    body_start = fence + len("```bash")
    body_end = section.find("```", body_start)
    if body_end == -1:
        pytest.fail("README Configuration section's ```bash block is not closed")

    secrets: dict[str, str] = {}
    dynamic: dict[str, str] = {}
    current: dict[str, str] | None = None
    for raw in section[body_start:body_end].splitlines():
        line = raw.strip()
        if line.startswith("#"):
            label = line.lstrip("#").strip().lower()
            if label.startswith("secrets"):
                current = secrets
            elif label.startswith("dynamic config"):
                current = dynamic
            continue
        match = _ENV_ASSIGNMENT.match(line)
        if match and current is not None:
            current[match.group("key")] = match.group("value").strip()

    if not secrets or not dynamic:
        pytest.fail(
            "README .env example lost its '# Secrets' or '# Dynamic config' section: "
            f"secrets={sorted(secrets)}, dynamic={sorted(dynamic)}"
        )
    return secrets, dynamic


def _readme_dynamic_config_block() -> dict[str, str]:
    """The JSON-valued env vars README teaches under ``# Dynamic config``."""
    return _readme_env_example()[1]


def _readme_documented_secrets() -> set[str]:
    """The secret env vars README teaches under ``# Secrets``; they drift the same way."""
    return set(_readme_env_example()[0])


def test_the_readme_env_example_loads_through_the_real_loader(monkeypatch) -> None:
    """Failure mode (a): the documented config must survive the real loader, not a fake."""
    import json

    from publisher_v2.config.loader import load_application_config

    monkeypatch.setattr("publisher_v2.config.loader.load_dotenv", lambda *args, **kwargs: None)
    for key in (
        "CAPTIONFILE_SETTINGS",
        "CONTENT_SETTINGS",
        "EMAIL_SERVER",
        "EMAIL_PASSWORD",
        "STORAGE_PROVIDER",
        "INSTA_PASSWORD",
        "TELEGRAM_BOT_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)

    secrets, documented = _readme_env_example()
    expected = {"STORAGE_PATHS", "PUBLISHERS", "OPENAI_SETTINGS"}
    assert expected <= documented.keys(), documented
    # Only what the README tells a reader to put in .env: a secret the loader
    # needs but README omits must fail here, not be papered over by the test.
    for key, value in {**secrets, **documented}.items():
        monkeypatch.setenv(key, value)

    config = load_application_config()

    storage = json.loads(documented["STORAGE_PATHS"])
    assert config.dropbox.image_folder == storage["root"] == "/Photos/my_folder"
    assert config.dropbox.archive_folder == f"{storage['root']}/{storage['archive']}" == "/Photos/my_folder/archive"

    (telegram_entry,) = [p for p in json.loads(documented["PUBLISHERS"]) if p["type"] == "telegram"]
    assert config.platforms.telegram_enabled is True
    assert config.telegram is not None
    assert config.telegram.channel_id == telegram_entry["channel_id"]

    openai_settings = json.loads(documented["OPENAI_SETTINGS"])
    assert config.openai.vision_model == openai_settings["vision_model"] == "gpt-4o"
    assert config.openai.caption_model == openai_settings["caption_model"] == "gpt-4o-mini"


_QUOTED_ENV_NAME = re.compile(r"[\"']([A-Z][A-Z0-9_]{2,})[\"']")


def _env_names_the_code_reads() -> set[str]:
    """Every whole-literal uppercase name in the package.

    Scoped to the whole package, not just `config/loader.py`: `WEB_AUTH_TOKEN`
    and the `FEATURE_*` flags are real variables read in `web/` and `utils/`,
    and a loader-only scan would reject them as invented.
    """
    src = REPO_ROOT / "publisher_v2" / "src" / "publisher_v2"
    return {name for path in src.rglob("*.py") for name in _QUOTED_ENV_NAME.findall(path.read_text())}


def test_every_env_var_the_readme_documents_is_one_the_code_reads() -> None:
    """An invented key (`FEATURE_ARCHIVE`) reads back as the default, so the loader test alone cannot catch it."""
    read_by_code = _env_names_the_code_reads()
    documented = set(_readme_dynamic_config_block()) | _readme_documented_secrets()
    assert documented, "the README config section stopped parsing"

    invented = sorted(key for key in documented if key not in read_by_code)

    assert not invented, (
        f"README documents env vars no module under publisher_v2/src reads: {invented}. "
        "Either the README is wrong, or the variable is read somewhere this scan does not cover."
    )


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


def test_ci_enables_the_slow_documented_command_check() -> None:
    """Failure mode (d): the exits-0 criterion is enforced only in CI, so the flag itself needs a guard."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "code-quality.yml").read_text()

    assert 'RUN_SLOW_DOC_CHECKS: "1"' in workflow, (
        "nothing would run the documented mypy command end to end if CI stops setting this"
    )
    # ...and it has to be on the step that runs pytest, not just present somewhere in the file.
    step = workflow[workflow.index("- name: Run tests with coverage") :]
    step = step[: step.index("\n    - name:", 1)]
    assert 'RUN_SLOW_DOC_CHECKS: "1"' in step, step
