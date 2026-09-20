"""#135 review follow-up: the isolation machinery itself needs guarding.

The conftest neutralises implicit `.env` loading and resets three kinds of
process-wide state. Each of those is a module-level singleton, so a gap in the
reset shows up as a test that passes alone and fails in a random order — the
exact failure #135 exists to remove. These tests pin the machinery instead of
waiting for a future ordering to expose it.
"""

from __future__ import annotations

# Imported as a top-level module: `publisher_v2/tests/` has no __init__.py and
# pytest runs in its default "prepend" import mode, which puts the rootdir on
# sys.path. Adding an __init__.py or switching to --import-mode=importlib would
# break this import.
import conftest as tests_conftest
import dotenv


def test_implicit_dotenv_loading_is_disabled() -> None:
    """A bare `load_dotenv()` must not copy a developer's workspace .env into os.environ."""
    assert dotenv.load_dotenv() is False
    assert dotenv.load_dotenv is tests_conftest._load_dotenv_explicit_only


def test_explicit_dotenv_paths_still_load(tmp_path) -> None:
    """Only implicit loads are disabled; an explicit path is a deliberate act."""
    env_file = tmp_path / "explicit.env"
    env_file.write_text("PV2_ISOLATION_PROBE=loaded\n")

    assert dotenv.load_dotenv(str(env_file)) is True


def test_a_stale_load_dotenv_reference_is_rebound() -> None:
    """A module imported BEFORE the conftest keeps its own copy of the real function.

    `from dotenv import load_dotenv` copies the object, so rebinding
    `dotenv.load_dotenv` alone would leave that module reading the real .env.
    """
    import publisher_v2.web.service as service

    original = service.load_dotenv
    try:
        service.load_dotenv = tests_conftest._real_load_dotenv  # simulate the pre-conftest import

        tests_conftest._neutralise_implicit_dotenv()

        assert service.load_dotenv is tests_conftest._load_dotenv_explicit_only
    finally:
        service.load_dotenv = original
