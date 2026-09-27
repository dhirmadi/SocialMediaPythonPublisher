"""
Shared pytest fixtures for publisher_v2 tests.

Fixtures defined here are automatically available to all tests in the
publisher_v2/tests directory and its subdirectories. Every fixture here must
have a user (PUB-084 AC6, ratcheted by test_suite_hygiene).

Shared fakes and builders (FakeOpenAI, BaseDummy*, stub_ai_service,
make_app_config) live in ``caption_pipeline_fakes`` — the single home for them;
the fixtures below are thin wrappers over that module.
"""

from __future__ import annotations

import os

# Set before any publisher_v2.web import: web/app.py raises at import time
# without a session secret, which would abort test collection in env-less CI.
os.environ.setdefault("WEB_SESSION_SECRET", "test_secret_key_for_testing_only")


from collections.abc import Callable, Generator
from typing import Any

import dotenv as _dotenv
import pytest
from caption_pipeline_fakes import FakeOpenAI, install_fake_openai

from publisher_v2.config.static_loader import get_static_config

# #135 (runs before any test module imports the app): web/service.py calls
# load_dotenv() at import time. Without this, a developer's workspace .env is
# copied into os.environ for the whole session and hides order dependencies
# that CI (no .env) then trips over. Only implicit loads are disabled; an
# explicit dotenv path still loads.
#
# Why this is a module-level rebind and not monkeypatch, and why _isolate_env
# ALSO patches publisher_v2.config.loader.load_dotenv per test: the two patches
# catch different moments.
#   - import-time: a module body running `load_dotenv()` fires once, during
#     collection, long before any fixture exists. Only a rebind done here, at
#     conftest import, is early enough.
#   - call-time: load_application_config() calls it inside a test, where
#     monkeypatch is the right tool because it unwinds afterwards.
# Removing either one leaves a real hole, so both stay.

_real_load_dotenv = _dotenv.load_dotenv


def _load_dotenv_explicit_only(dotenv_path=None, *args, **kwargs):  # type: ignore[no-untyped-def]
    # A `stream=` load is as deliberate as a path, so it is not an implicit load.
    if dotenv_path or kwargs.get("stream") is not None:
        return _real_load_dotenv(dotenv_path, *args, **kwargs)
    return False


def _neutralise_implicit_dotenv() -> None:
    """Rebind `dotenv.load_dotenv`, and any stale copy of it already taken.

    `from dotenv import load_dotenv` copies the function object. A module
    imported BEFORE this conftest keeps the real one and would still read the
    developer's .env, so rebinding `dotenv.load_dotenv` alone is not enough.
    Modules imported after this point pick up the replacement automatically.
    """
    import sys

    _dotenv.load_dotenv = _load_dotenv_explicit_only
    for module in list(sys.modules.values()):
        name = getattr(module, "__name__", "")
        if name.startswith("publisher_v2") and getattr(module, "load_dotenv", None) is _real_load_dotenv:
            module.load_dotenv = _load_dotenv_explicit_only


_neutralise_implicit_dotenv()


@pytest.fixture(autouse=True)
def _bust_static_config_cache() -> Generator[None, None, None]:
    """Reset the @lru_cache on get_static_config so tests that edit YAML defaults
    (e.g. PUB-046 platform_captions) don't leak cached state to subsequent tests.
    """
    get_static_config.cache_clear()
    yield
    get_static_config.cache_clear()


# ==============================================================================
# ENVIRONMENT ISOLATION FIXTURES
# ==============================================================================


def reset_web_rate_limiters() -> None:
    """Reset every limiter publisher_v2.web.app holds, discovered, not listed.

    A hard-coded name list silently stops covering a limiter added later; this
    finds them by type, so a new one is reset the day it is introduced.
    """
    import sys

    app_module = sys.modules.get("publisher_v2.web.app")
    if app_module is None:
        return
    # Imported lazily: the app module is already loaded whenever this matters,
    # and a top-level web import here would run at conftest-collection time.
    from publisher_v2.web.rate_limit import SlidingWindowLimiter

    # Every loaded web module, not just web.app: a limiter defined in a router
    # would otherwise be invisible to both this reset and the test guarding it.
    for module in [m for name, m in list(sys.modules.items()) if name.startswith("publisher_v2.web") and m]:
        for limiter in vars(module).values():
            if isinstance(limiter, SlidingWindowLimiter):
                limiter.reset()


_shared_http_client_reset_count = 0


def reset_shared_http_client() -> None:
    """Drop the process-wide httpx client so a test never inherits another's.

    `services/_http.py` caches one `AsyncClient` in a module global. Nothing
    leaks today, but the global outlives every test and only one test resets it
    by hand; doing it here makes that independent of who ran first.

    The client is dropped, not closed: no test opens a real connection (the one
    test that reaches `get_shared_client` fakes `httpx.AsyncClient`), and httpx's
    client defines no `__del__`, so dropping it is silent. If a test ever lets a
    real connection open, this needs `aclose_shared_client()` run on a loop.
    """
    global _shared_http_client_reset_count

    from publisher_v2.services import _http

    _http._client = None
    _shared_http_client_reset_count += 1


@pytest.fixture(autouse=True)
def _reset_shared_http_client() -> Generator[None, None, None]:
    reset_shared_http_client()
    yield
    reset_shared_http_client()


@pytest.fixture(autouse=True)
def _reset_web_rate_limiters() -> Generator[None, None, None]:
    """#135: reset the process-wide limiters in publisher_v2.web.app around every test.

    They are module-level singletons; without a reset a login/analyze/publish test
    can hit 429 depending on how many earlier tests used the same key. Only acts
    once the app module is imported, so non-web tests do not import the app.
    """
    reset_web_rate_limiters()
    yield
    reset_web_rate_limiters()


@pytest.fixture(autouse=True)
def _isolate_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Generator[None, None, None]:
    """
    Ensure tests don't leak environment variables.

    Clears commonly used env vars that could affect test isolation.
    This runs automatically for all tests.

    PUB-084: points XDG_CACHE_HOME at a fresh per-test temp dir so the posted-state
    dedup cache (utils.state) and the Instagram session store never touch the real
    ~/.cache and never carry state between tests. Test files must not set it themselves.

    Patches load_dotenv to prevent the workspace .env from being loaded
    during tests (unless an explicit env_path is provided to load_application_config).
    """
    from unittest.mock import patch

    # Clear environment variables that might leak between tests
    env_vars_to_clear = [
        # Auth-related
        "WEB_AUTH_TOKEN",
        "WEB_AUTH_USER",
        "WEB_AUTH_PASS",
        # Auth0-related
        "AUTH0_DOMAIN",
        "AUTH0_CLIENT_ID",
        "AUTH0_CLIENT_SECRET",
        "AUTH0_AUTHORIZED_EMAILS",
        # Session/security
        "WEB_SESSION_SECRET",
        "SECRET_KEY",
        # Debug flags
        "WEB_DEBUG",
        # Orchestrator-related (prevent tenant middleware from activating)
        "ORCHESTRATOR_BASE_URL",
        "ORCHESTRATOR_SERVICE_TOKEN",
        "ORCHESTRATOR_SERVICE_TOKEN_PRIMARY",
        "ORCHESTRATOR_SERVICE_TOKEN_SECONDARY",
        "CONFIG_SOURCE",
        # Env-first configuration vars (prevent workspace .env from interfering)
        "STORAGE_PATHS",
        "PUBLISHERS",
        "OPENAI_SETTINGS",
        "EMAIL_SERVER",
        "CONTENT_SETTINGS",
        "CAPTIONFILE_SETTINGS",
        "CONFIRMATION_SETTINGS",
    ]
    for var in env_vars_to_clear:
        monkeypatch.delenv(var, raising=False)

    # Set minimal required env vars for tests
    monkeypatch.setenv("WEB_DEBUG", "1")  # Enable dev mode for tests
    monkeypatch.setenv("WEB_SESSION_SECRET", "test_secret_key_for_testing_only")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path_factory.mktemp("xdg-cache")))

    # Patch load_dotenv to be a no-op when called without arguments
    # This prevents the workspace .env from being loaded during tests
    from dotenv import load_dotenv as real_load_dotenv

    def noop_load_dotenv(dotenv_path=None, **kwargs):
        """Only load if an explicit path is provided."""
        if dotenv_path:
            return real_load_dotenv(dotenv_path, **kwargs)
        # Don't load workspace .env automatically
        return False

    with patch("publisher_v2.config.loader.load_dotenv", noop_load_dotenv):
        yield


@pytest.fixture
def mock_dropbox_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up minimal Dropbox environment variables for config loading."""
    monkeypatch.setenv("DROPBOX_APP_KEY", "test_app_key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "test_app_secret")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh_token")


@pytest.fixture
def mock_openai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up minimal OpenAI environment variables for config loading."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-for-testing-purposes-only")


@pytest.fixture
def mock_full_env(mock_dropbox_env: None, mock_openai_env: None) -> None:
    """Set up all required environment variables for full config loading."""
    pass  # Dependencies handle the setup


@pytest.fixture
def env_first_config(monkeypatch: pytest.MonkeyPatch, mock_full_env: None) -> Generator[None, None, None]:
    """#135: minimal env-first configuration (INI support was removed in #97).

    Tests that build the real app/service must request this instead of relying
    on env vars leaked by an earlier test or by a workspace .env. Clears the
    config-source and web-service caches on both sides so no instance outlives
    the test.
    """
    monkeypatch.setenv("CONFIG_SOURCE", "env")
    monkeypatch.setenv("STORAGE_PATHS", '{"root": "/Photos", "archive": "archive"}')
    monkeypatch.setenv("PUBLISHERS", "[]")
    monkeypatch.setenv("OPENAI_SETTINGS", "{}")
    monkeypatch.delenv("CONFIG_PATH", raising=False)
    from publisher_v2.config.source import get_config_source
    from publisher_v2.web.dependencies import get_service

    get_config_source.cache_clear()
    get_service.cache_clear()
    yield
    get_config_source.cache_clear()
    get_service.cache_clear()


# ==============================================================================
# EXTERNAL-SERVICE FAKES
# ==============================================================================


@pytest.fixture
def fake_openai(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeOpenAI]:
    """Build a ``FakeOpenAI`` and install it as ``publisher_v2.services.ai.AsyncOpenAI``.

    Call it with FakeOpenAI's arguments, e.g. ``fake_openai(script=["reply", RuntimeError("x")])``
    or ``fake_openai(["telegram"])``; it returns the installed fake. Clients built after a later
    call get that later fake.
    """

    def _install(*args: Any, **kwargs: Any) -> FakeOpenAI:
        return install_fake_openai(monkeypatch, FakeOpenAI(*args, **kwargs))

    return _install
