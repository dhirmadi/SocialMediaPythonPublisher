"""PUB-055 AC6: `scripts/pip_audit_ignore.py` validates the accepted-advisory list.

An ignore file is a hole in the dependency gate, so the loader has to refuse an
entry that is undocumented (no `reason`), open-ended (no `expires`) or stale
(`expires` in the past) rather than quietly widening the hole. `today` is
injected — the tests never depend on the real clock.

`scripts/` has no `__init__.py`, so the module is loaded by path, the same way
`test_caption_sample_script.py` loads `scripts/caption_sample.py`.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "pip_audit_ignore.py"


def _module() -> Any:
    assert SCRIPT.exists(), "scripts/pip_audit_ignore.py does not exist"
    spec = importlib.util.spec_from_file_location("pip_audit_ignore", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ignore_file(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "pip-audit-ignore.toml"
    path.write_text(body)
    return path


def test_an_expired_entry_raises_instead_of_silently_passing(tmp_path: Path) -> None:
    """AC6: a lapsed acceptance forces a re-review; it is not applied anyway."""
    path = _ignore_file(
        tmp_path,
        """
[[ignore]]
id = "GHSA-expired-0000-0000"
reason = "No upstream fix at the time it was accepted."
expires = "2026-01-31"
""",
    )

    with pytest.raises(ValueError) as excinfo:
        _module().load_ignore_entries(path, today=date(2026, 2, 1))

    assert "GHSA-expired-0000-0000" in str(excinfo.value)


def test_unexpired_entries_yield_their_ignore_vuln_flags(tmp_path: Path) -> None:
    """AC6: valid, unexpired entries become the pip-audit `--ignore-vuln` arguments."""
    path = _ignore_file(
        tmp_path,
        """
[[ignore]]
id = "GHSA-aaaa-1111-bbbb"
reason = "Vulnerable code path is not reachable from this app."
expires = "2026-12-31"

[[ignore]]
id = "GHSA-cccc-2222-dddd"
reason = "Fix landed upstream but is unreleased."
expires = "2027-06-30"
""",
    )

    ignored = _module().load_ignore_entries(path, today=date(2026, 9, 26))

    assert ignored == ["GHSA-aaaa-1111-bbbb", "GHSA-cccc-2222-dddd"]


def test_an_entry_expiring_today_is_still_honoured(tmp_path: Path) -> None:
    """The contract raises on `today > expires`, so the expiry day itself still applies."""
    path = _ignore_file(
        tmp_path,
        """
[[ignore]]
id = "GHSA-edge-3333-eeee"
reason = "Accepted until the pinned release ships."
expires = "2026-09-26"
""",
    )

    assert _module().load_ignore_entries(path, today=date(2026, 9, 26)) == ["GHSA-edge-3333-eeee"]


def test_an_entry_without_an_id_raises(tmp_path: Path) -> None:
    path = _ignore_file(
        tmp_path,
        """
[[ignore]]
reason = "Someone forgot which advisory this is about."
expires = "2026-12-31"
""",
    )

    with pytest.raises(ValueError) as excinfo:
        _module().load_ignore_entries(path, today=date(2026, 1, 1))

    assert "id" in str(excinfo.value)


def test_an_entry_without_a_reason_raises(tmp_path: Path) -> None:
    path = _ignore_file(
        tmp_path,
        """
[[ignore]]
id = "GHSA-noreason-4444-ffff"
expires = "2026-12-31"
""",
    )

    with pytest.raises(ValueError) as excinfo:
        _module().load_ignore_entries(path, today=date(2026, 1, 1))

    assert "GHSA-noreason-4444-ffff" in str(excinfo.value)
    assert "reason" in str(excinfo.value)


def test_an_entry_without_an_expires_date_raises(tmp_path: Path) -> None:
    path = _ignore_file(
        tmp_path,
        """
[[ignore]]
id = "GHSA-noexpiry-5555-9999"
reason = "An ignore with no end date is a permanent silent skip."
""",
    )

    with pytest.raises(ValueError) as excinfo:
        _module().load_ignore_entries(path, today=date(2026, 1, 1))

    assert "GHSA-noexpiry-5555-9999" in str(excinfo.value)
    assert "expires" in str(excinfo.value)


def test_a_file_with_no_ignore_key_yields_no_entries(tmp_path: Path) -> None:
    """The committed file starts as a header comment only — that is valid, not a parse error."""
    path = _ignore_file(tmp_path, "# Accepted advisories pip-audit must skip. None today.\n")

    assert _module().load_ignore_entries(path, today=date(2026, 1, 1)) == []


# --- CLI contract -----------------------------------------------------------
#
# The workflow consumes `main()` as `IGNORE_ARGS=$(... pip_audit_ignore.py)` and
# relies on two things: the exact `--ignore-vuln <id>` rendering on stdout, and
# a non-zero exit *before* pip-audit runs when the ignore file is unusable.
# `main()` does not take an injected `today`, so these fixtures use expiry dates
# far outside any plausible run date instead of the current clock.


def test_main_prints_the_ignore_vuln_tokens_for_a_valid_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC6: stdout is exactly the token string the pip-audit invocation splices in."""
    path = _ignore_file(
        tmp_path,
        """
[[ignore]]
id = "GHSA-aaaa-1111-bbbb"
reason = "Vulnerable code path is not reachable from this app."
expires = "2999-12-31"

[[ignore]]
id = "GHSA-cccc-2222-dddd"
reason = "Fix landed upstream but is unreleased."
expires = "2999-12-31"
""",
    )

    exit_code = _module().main(["--path", str(path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == "--ignore-vuln GHSA-aaaa-1111-bbbb --ignore-vuln GHSA-cccc-2222-dddd"
    assert captured.err == ""


def test_main_fails_closed_on_an_expired_entry(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """AC6: a stale ignore file must exit non-zero and emit no tokens, so CI stops here."""
    path = _ignore_file(
        tmp_path,
        """
[[ignore]]
id = "GHSA-expired-0000-0000"
reason = "No upstream fix at the time it was accepted."
expires = "2020-01-31"
""",
    )

    exit_code = _module().main(["--path", str(path)])

    captured = capsys.readouterr()
    assert exit_code == 1, "an expired ignore entry must fail the step, not be applied anyway"
    assert "--ignore-vuln" not in captured.out
    assert "GHSA-expired-0000-0000" in captured.err


def test_main_fails_closed_on_malformed_toml(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A file that cannot be parsed must not silently degrade to an empty ignore list."""
    path = _ignore_file(tmp_path, '[[ignore]\nid = "GHSA-broken"\n')

    exit_code = _module().main(["--path", str(path)])

    captured = capsys.readouterr()
    assert exit_code == 1, "unparseable TOML must fail the step rather than fail open"
    assert "--ignore-vuln" not in captured.out


def test_main_fails_closed_on_a_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A renamed or deleted ignore file is a configuration error, not an empty ignore list."""
    missing = tmp_path / "does-not-exist.toml"

    exit_code = _module().main(["--path", str(missing)])

    captured = capsys.readouterr()
    assert exit_code == 1, "a missing ignore file must fail the step rather than fail open"
    assert "--ignore-vuln" not in captured.out


def test_main_prints_no_tokens_for_a_header_only_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The committed file is comment-only today: exit 0 with an empty `IGNORE_ARGS`."""
    path = _ignore_file(tmp_path, "# Accepted advisories pip-audit must skip. None today.\n")

    exit_code = _module().main(["--path", str(path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == ""
    assert "--ignore-vuln" not in captured.out
