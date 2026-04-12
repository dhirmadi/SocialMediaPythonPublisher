"""Feature flag resolution helpers."""

from __future__ import annotations

import os

from publisher_v2.config.schema import ApplicationConfig


def resolve_library_enabled(config: ApplicationConfig) -> bool:
    """Resolve whether the library feature should be enabled.

    Logic:
    - If FEATURE_LIBRARY env var is set, it takes precedence (true/false).
    - Otherwise, auto-enable when config.managed is not None.
    - Default False for Dropbox-only instances.
    """
    env_val = os.environ.get("FEATURE_LIBRARY", "").strip().lower()
    if env_val in ("true", "1", "yes"):
        return True
    if env_val in ("false", "0", "no"):
        return False
    # No env override — auto-enable for managed storage
    return config.managed is not None
