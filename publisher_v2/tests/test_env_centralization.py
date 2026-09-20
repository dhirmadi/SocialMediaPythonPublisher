"""#97 stage 2: environment reads are centralized.

``os.environ`` / ``os.getenv`` may appear only in the allowed modules below.
Everything else must go through ``config/runtime_settings.py`` (tunables) or
the config loaders.

The expectation is the *contents* of each exception, not merely its name: for
every allowed module this file pins the exact set of environment variables it
reads. Pinning only the module names let a ratified module grow new ad-hoc
reads silently, and a test that compared the allow-list against a second copy
of itself in the same file could not fail at all — editing one constant and not
the other is not a mistake anyone makes.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "publisher_v2"

# Env accessors: ``os.environ[...]``, ``os.environ.get(...)``, ``os.getenv(...)``
# and ``web/auth.py``'s own ``_get_env`` wrapper around them.
_ENV_HELPERS = {"_get_env"}

# Every module outside ``config/`` that may read the environment, with the exact
# variables it reads. #143 shrank this: web/middleware.py, web/middleware_security.py,
# web/rate_limit.py and services/managed_storage.py now take their tunables from
# RuntimeSettings, and web/auth.py's set_admin_cookie no longer parses
# WEB_SECURE_COOKIES itself. Adding a name here means adding an ad-hoc env read
# outside the config layer — it has to be argued for in review.
EXPECTED_ENV_READS: dict[str, frozenset[str]] = {
    # Auth reads WEB_AUTH_*/session secrets at request time by design.
    "web/auth.py": frozenset(
        {
            "AUTH0_CLIENT_ID",
            "AUTH0_DOMAIN",
            "SECRET_KEY",
            "WEB_ADMIN_COOKIE_EPOCH",
            "WEB_ADMIN_COOKIE_TTL_SECONDS",
            "WEB_ALLOW_UNAUTHENTICATED",
            "WEB_AUTH_PASS",
            "WEB_AUTH_TOKEN",
            "WEB_AUTH_USER",
            "WEB_DEV_INSECURE_SECRET",
            "WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE",
            "WEB_SESSION_SECRET",
        }
    ),
    # Module-level session secret / dev-insecure bootstrap (+ WEB_DEBUG log level).
    "web/app.py": frozenset({"DYNO", "SECRET_KEY", "WEB_DEBUG", "WEB_DEV_INSECURE_SECRET", "WEB_SESSION_SECRET"}),
    # CONFIG_PATH / ENV_PATH standalone bootstrap.
    "web/service.py": frozenset({"CONFIG_PATH", "ENV_PATH"}),
    "db/__init__.py": frozenset({"DATABASE_URL"}),  # DATABASE_URL presence check
    "utils/state.py": frozenset({"XDG_CACHE_HOME"}),  # cache location
    # WEB_SESSION_SECRET/SECRET_KEY (#94 session encryption key, same category as
    # web/auth.py) and XDG_CACHE_HOME (same category as utils/state.py).
    "services/instagram_session.py": frozenset({"SECRET_KEY", "WEB_SESSION_SECRET", "XDG_CACHE_HOME"}),
    # Standalone CLI with its own env contract.
    "tools/migrate_storage.py": frozenset(
        {
            "DROPBOX_APP_KEY",
            "DROPBOX_APP_SECRET",
            "MIGRATE_DROPBOX_REFRESH_TOKEN",
            "R2_ACCESS_KEY_ID",
            "R2_BUCKET_NAME",
            "R2_ENDPOINT_URL",
            "R2_REGION",
            "R2_SECRET_ACCESS_KEY",
        }
    ),
}

# Reads whose variable name is not a literal, so the scan cannot resolve it.
# Both are accessors over a name supplied by the caller or a module constant,
# not additional variables: web/auth.py's ``_get_env(name)`` body and
# migrate_storage's loop over ``REQUIRED_ENV_VARS``.
EXPECTED_DYNAMIC_READS: dict[str, int] = {
    "web/auth.py": 1,
    "tools/migrate_storage.py": 1,
}


def _env_reads(path: Path) -> tuple[set[str], int]:
    """(variable names read from a literal, count of reads with a computed name)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    dynamic = 0

    def _record(node: ast.expr | None) -> None:
        nonlocal dynamic
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
        else:
            dynamic += 1

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            is_env_call = (
                (isinstance(func, ast.Attribute) and func.attr == "getenv" and _is_os(func.value))
                or (
                    isinstance(func, ast.Attribute)
                    and func.attr == "get"
                    and isinstance(func.value, ast.Attribute)
                    and func.value.attr == "environ"
                    and _is_os(func.value.value)
                )
                or (isinstance(func, ast.Name) and func.id in _ENV_HELPERS)
            )
            if is_env_call and node.args:
                _record(node.args[0])
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "environ"
            and _is_os(node.value.value)
        ):
            _record(node.slice if isinstance(node.slice, ast.expr) else None)
    return names, dynamic


def _is_os(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id == "os"


def _touches_environ(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv") and _is_os(node.value)
        for node in ast.walk(tree)
    )


def _module_paths() -> list[str]:
    return [str(p.relative_to(SRC)) for p in sorted(SRC.rglob("*.py"))]


def test_env_reads_only_in_allowed_modules() -> None:
    """The config package owns env reading; everything else needs an entry above."""
    offenders = [
        rel
        for rel in _module_paths()
        if not rel.startswith("config/") and rel not in EXPECTED_ENV_READS and _touches_environ(SRC / rel)
    ]
    assert not offenders, f"Ad-hoc os.environ reads outside allowed modules: {offenders}"


def test_allowed_modules_read_exactly_the_pinned_variables() -> None:
    """An allowed module may not quietly grow a new ad-hoc env read."""
    actual = {rel: _env_reads(SRC / rel)[0] for rel in EXPECTED_ENV_READS}
    drift = {
        rel: {"added": sorted(names - EXPECTED_ENV_READS[rel]), "removed": sorted(EXPECTED_ENV_READS[rel] - names)}
        for rel, names in actual.items()
        if names != EXPECTED_ENV_READS[rel]
    }
    assert not drift, f"Env reads drifted from the pinned set: {drift}"


def test_computed_env_reads_do_not_multiply() -> None:
    """A read whose name is computed hides from the pinned set, so its count is pinned too."""
    actual = {rel: _env_reads(SRC / rel)[1] for rel in EXPECTED_ENV_READS}
    expected = {rel: EXPECTED_DYNAMIC_READS.get(rel, 0) for rel in EXPECTED_ENV_READS}
    assert actual == expected


def test_every_pinned_module_still_exists() -> None:
    """The pinned list may only shrink by deleting the read, not by renaming the file."""
    missing = [rel for rel in EXPECTED_ENV_READS if not (SRC / rel).exists()]
    assert not missing, f"Pinned modules no longer exist: {missing}"
