"""#97 stage 2: environment reads are centralized.

``os.environ`` / ``os.getenv`` may appear only in the allowed modules below.
Everything else must go through ``config/runtime_settings.py`` (tunables) or
the config loaders.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "publisher_v2"

# Modules allowed to read the environment directly.
ALLOWED = {
    # The config layer is where env reading belongs.
    "config",  # whole package
    # Auth reads WEB_AUTH_*/session secrets at request time by design.
    "web/auth.py",
    # Documented bootstrap/mode-selection exceptions (#97 stage 2 — candidates
    # for later stages, listed explicitly so new reads still fail this test):
    "web/app.py",  # module-level session secret / debug / cookie bootstrap
    "web/middleware.py",  # CONFIG_SOURCE / ORCHESTRATOR_BASE_URL mode selection
    "web/middleware_security.py",  # WEB_SECURE_COOKIES header hardening
    "web/rate_limit.py",  # WEB_TRUST_FORWARDED_FOR proxy trust
    "web/service.py",  # CONFIG_PATH / ENV_PATH standalone bootstrap
    "db/__init__.py",  # DATABASE_URL presence check
    "utils/state.py",  # XDG_CACHE_HOME cache location
    "services/managed_storage.py",  # WEB_THUMBNAIL_CACHE_* (PUB-031 thumbnails)
    "services/instagram_session.py",  # WEB_SESSION_SECRET/SECRET_KEY (#94 session
    # encryption key, same category as web/auth.py) and XDG_CACHE_HOME (same
    # category as utils/state.py)
    "tools/migrate_storage.py",  # standalone CLI with its own env contract
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
