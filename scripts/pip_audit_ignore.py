#!/usr/bin/env python3
r"""Read and validate `.github/pip-audit-ignore.toml` (PUB-055).

An ignore list is a hole in the dependency gate, so every accepted advisory has
to carry an `id`, a `reason` and an ISO-8601 `expires` date. A lapsed entry is a
hard error rather than a silent permanent skip: CI then fails on the stale
ignore file *before* pip-audit runs, which forces a re-review.

Usage::

    IGNORE_ARGS=$(uv run python scripts/pip_audit_ignore.py)
    uv export --frozen --no-emit-project --all-groups --no-hashes --format requirements-txt -o requirements-audit.txt
    uvx --from 'pip-audit==2.10.1' pip-audit --no-deps --disable-pip -r requirements-audit.txt \
      -f json -o pip-audit-report.json $IGNORE_ARGS
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

DEFAULT_IGNORE_FILE = Path(".github") / "pip-audit-ignore.toml"

# `$IGNORE_ARGS` is deliberately word-split on the shell command line, so an id may only
# contain advisory-identifier characters -- never whitespace, globs or shell metacharacters.
_VALID_ID = re.compile(r"[A-Za-z0-9._-]+")


def _parse_expires(value: Any, entry_id: str) -> date:
    """Accept a native TOML date or an ISO-8601 `YYYY-MM-DD` string."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"ignore entry `{entry_id}` has an unparseable `expires` value: {value!r}") from exc
    raise ValueError(f"ignore entry `{entry_id}` has an unparseable `expires` value: {value!r}")


def load_ignore_entries(path: Path, today: date | None = None) -> list[str]:
    """Return the advisory ids to pass to pip-audit as `--ignore-vuln`.

    Raises `ValueError` naming the offending entry when it is missing `id`,
    `reason` or `expires`, when its `id` is not a bare advisory identifier, or
    when its `expires` date has already passed.
    A file with no top-level `ignore` key yields no entries.
    """
    today = today or datetime.now(UTC).date()
    document = tomllib.loads(Path(path).read_text(encoding="utf-8"))

    ignored: list[str] = []
    for index, entry in enumerate(document.get("ignore") or []):
        if not isinstance(entry, dict):
            raise ValueError(
                f"ignore entry #{index + 1} in {path} is not a table; "
                "each accepted advisory must be an `[[ignore]]` table with `id`, `reason` and `expires`"
            )

        raw_id = entry.get("id")
        if raw_id is not None and not isinstance(raw_id, str):
            raise ValueError(f"ignore entry #{index + 1} in {path} has a non-string `id`: {raw_id!r}")

        entry_id = (raw_id or "").strip()
        if not entry_id:
            raise ValueError(f"ignore entry #{index + 1} in {path} is missing a required `id`")

        if not _VALID_ID.fullmatch(entry_id):
            raise ValueError(
                f"ignore entry `{entry_id}` in {path} has an invalid `id`: "
                "advisory ids may only contain letters, digits, `.`, `_` and `-`"
            )

        if not str(entry.get("reason") or "").strip():
            raise ValueError(f"ignore entry `{entry_id}` in {path} is missing a required `reason`")

        if entry.get("expires") is None:
            raise ValueError(f"ignore entry `{entry_id}` in {path} is missing a required `expires` date")

        expires = _parse_expires(entry["expires"], entry_id)
        if today > expires:
            raise ValueError(
                f"ignore entry `{entry_id}` in {path} expired on {expires.isoformat()}; "
                "re-review the advisory and either drop the entry or extend its `expires` date"
            )

        ignored.append(entry_id)

    return ignored


def main(argv: list[str] | None = None) -> int:
    """Print the `--ignore-vuln <id>` tokens for the ignore file, or fail loudly."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_IGNORE_FILE,
        help=f"path to the ignore file (default: {DEFAULT_IGNORE_FILE})",
    )
    args = parser.parse_args(argv)

    try:
        ignored = load_ignore_entries(args.path)
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(" ".join(f"--ignore-vuln {vuln_id}" for vuln_id in ignored))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
