"""#97 stage 2: environment reads are centralized.

``os.environ`` / ``os.getenv`` may appear only in the allowed modules below.
Everything else must go through ``config/runtime_settings.py`` (tunables) or
the config loaders.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "publisher_v2"

# Modules allowed to read the environment directly. #143 shrank this list:
# web/middleware.py, web/middleware_security.py, web/rate_limit.py and
# services/managed_storage.py now take their tunables from RuntimeSettings.
ALLOWED = {
    # The config layer is where env reading belongs.
    "config",  # whole package
    # Auth reads WEB_AUTH_*/session secrets at request time by design.
    "web/auth.py",
    # Documented bootstrap exceptions (listed explicitly so new reads still fail this test):
    "web/app.py",  # module-level session secret / dev-insecure bootstrap (+ WEB_DEBUG log level)
    "web/service.py",  # CONFIG_PATH / ENV_PATH standalone bootstrap
    "db/__init__.py",  # DATABASE_URL presence check
    "utils/state.py",  # XDG_CACHE_HOME cache location
    "services/instagram_session.py",  # WEB_SESSION_SECRET/SECRET_KEY (#94 session
    # encryption key, same category as web/auth.py) and XDG_CACHE_HOME (same
    # category as utils/state.py)
    "tools/migrate_storage.py",  # standalone CLI with its own env contract
}

# #143: the exact set of modules allowed to read the environment. This constant
# only ever moves down — adding a module here must be argued for in review, and
# the test below fails on any new entry rather than on a generous upper bound.
EXPECTED_ALLOWED = {
    "config",
    "web/auth.py",
    "web/app.py",
    "web/service.py",
    "db/__init__.py",
    "utils/state.py",
    "services/instagram_session.py",
    "tools/migrate_storage.py",
}


def _reads_env(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in ("environ", "getenv")
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        ):
            return True
    return False


def _is_allowed(rel: str) -> bool:
    return rel in ALLOWED or rel.startswith("config/")


def test_env_reads_only_in_allowed_modules() -> None:
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        rel = str(path.relative_to(SRC))
        if _is_allowed(rel):
            continue
        if _reads_env(path):
            offenders.append(rel)
    assert not offenders, f"Ad-hoc os.environ reads outside allowed modules: {offenders}"


def test_allow_list_does_not_grow() -> None:
    """#143: the allow-list is exact, so a future ad-hoc env read cannot be waved through."""
    assert ALLOWED == EXPECTED_ALLOWED, (
        "The env allow-list changed. It may only shrink: "
        f"added={sorted(ALLOWED - EXPECTED_ALLOWED)} removed={sorted(EXPECTED_ALLOWED - ALLOWED)}"
    )
