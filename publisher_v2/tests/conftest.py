"""
Shared pytest fixtures for publisher_v2 tests.

This file provides common fixtures used across multiple test modules to:
1. Reduce code duplication (QC-001 DRY compliance)
2. Ensure consistent test setup
3. Make tests more maintainable

Fixtures defined here are automatically available to all tests in the
publisher_v2/tests directory and its subdirectories.

FIXTURE INVENTORY (QC-001 Centralization):
- DummyStorage variants: Base storage mock with configurable responses
- DummyAnalyzer: Vision analyzer mock returning ImageAnalysis
- DummyGenerator: Caption generator mock
- DummyAI: AIService mock with analyzer + generator
- DummyPublisher: Publisher mock for workflow tests
- DummyClient: Dropbox client mock for low-level storage tests
"""

from __future__ import annotations

import os

# Set before any publisher_v2.web import: web/app.py raises at import time
# without a session secret, which would abort test collection in env-less CI.
os.environ.setdefault("WEB_SESSION_SECRET", "test_secret_key_for_testing_only")


from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import dotenv as _dotenv
import pytest

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
)
from publisher_v2.config.static_loader import get_static_config
from publisher_v2.core.models import CaptionSpec, ImageAnalysis, PublishResult
from publisher_v2.services.storage_protocol import FileMetadata

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
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """
    Ensure tests don't leak environment variables.

    Clears commonly used env vars that could affect test isolation.
    This runs automatically for all tests.

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
# CONFIGURATION FIXTURES
# ==============================================================================


@pytest.fixture
def minimal_ini_content() -> str:
    """Generate minimal valid INI configuration content."""
    return """
[dropbox]
image_folder = /Photos
archive_folder = Archive

[openai]
; No config needed - uses env vars

[content]
hashtag_string = #test
archive = false
debug = false
"""


@pytest.fixture
def minimal_features_config() -> SimpleNamespace:
    """Create a minimal features configuration for testing."""
    return SimpleNamespace(
        analyze_caption_enabled=True,
        publish_enabled=True,
        keep_enabled=True,
        remove_enabled=True,
        auto_view_enabled=False,
    )


@pytest.fixture
def minimal_platforms_config() -> SimpleNamespace:
    """Create a minimal platforms configuration for testing."""
    return SimpleNamespace(
        telegram_enabled=False,
        instagram_enabled=False,
        email_enabled=False,
    )


@pytest.fixture
def minimal_app_config(
    minimal_features_config: SimpleNamespace,
    minimal_platforms_config: SimpleNamespace,
) -> SimpleNamespace:
    """Create a minimal application configuration for testing."""
    return SimpleNamespace(
        features=minimal_features_config,
        platforms=minimal_platforms_config,
        telegram=None,
        instagram=None,
        email=None,
        auth0=None,
    )


@pytest.fixture
def standard_dropbox_config() -> DropboxConfig:
    """Standard DropboxConfig for workflow tests."""
    return DropboxConfig(
        app_key="test_key",
        app_secret="test_secret",
        refresh_token="test_refresh",
        image_folder="/Photos",
        archive_folder="archive",
    )


@pytest.fixture
def standard_openai_config() -> OpenAIConfig:
    """Standard OpenAIConfig for AI service tests."""
    return OpenAIConfig(
        api_key="sk-test-key-for-testing",
        vision_model="gpt-4o",
        caption_model="gpt-4o-mini",
        sd_caption_enabled=True,
        sd_caption_single_call_enabled=True,
    )


@pytest.fixture
def standard_app_config(
    standard_dropbox_config: DropboxConfig,
    standard_openai_config: OpenAIConfig,
) -> ApplicationConfig:
    """Standard ApplicationConfig for workflow tests."""
    return ApplicationConfig(
        dropbox=standard_dropbox_config,
        storage_paths=StoragePathConfig(image_folder="/Photos"),
        openai=standard_openai_config,
        platforms=PlatformsConfig(
            telegram_enabled=False,
            instagram_enabled=False,
            email_enabled=False,
        ),
        telegram=None,
        instagram=None,
        email=None,
        content=ContentConfig(hashtag_string="#test", archive=False, debug=False),
    )


# ==============================================================================
# DUMMY STORAGE FIXTURES (QC-001)
# ==============================================================================


class BaseDummyStorage:
    """
    Base dummy storage class that can be customized per test.

    This centralizes the common storage mock pattern found across 8+ test files.
    Subclasses or instances can override specific methods as needed.
    """

    def __init__(
        self,
        config: DropboxConfig | None = None,
        images: list[str] | None = None,
        content: bytes = b"\x89PNG\r\n\x1a\n",
    ) -> None:
        self.config = config or DropboxConfig(
            app_key="k",
            app_secret="s",
            refresh_token="r",
            image_folder="/Photos",
            archive_folder="archive",
        )
        self._images = images or ["test.jpg"]
        self._content = content
        # Track operations for assertions
        self.sidecar_text: str | None = None
        self.sidecars_written: int = 0
        self.archives: int = 0
        self.moves: list[tuple[str, str, str]] = []  # (folder, filename, target)

    async def list_images(self, folder: str) -> list[str]:
        return self._images

    async def download_image(self, folder: str, filename: str) -> bytes:
        return self._content

    async def get_temporary_link(self, folder: str, filename: str) -> str:
        return f"https://example.com/tmp/{filename}"

    async def get_file_metadata(self, folder: str, filename: str) -> FileMetadata:
        return FileMetadata(file_id="id:XYZ", revision="123", modified_at=None, size=None)

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        self.sidecar_text = text
        self.sidecars_written += 1

    async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None:
        return None  # Default: no sidecar

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        self.archives += 1

    async def move_image_with_sidecars(self, folder: str, filename: str, target: str) -> None:
        self.moves.append((folder, filename, target))

    async def delete_file_with_sidecar(self, folder: str, filename: str) -> None:
        pass

    async def ensure_folder_exists(self, folder_path: str) -> None:
        pass

    async def list_images_with_hashes(self, folder: str) -> list[tuple[str, str]]:
        return [(name, "") for name in self._images]

    async def get_thumbnail(
        self,
        folder: str,
        filename: str,
        size: object = None,
        format: object = None,
    ) -> bytes:
        return b"\xff\xd8\xff\xe0"  # minimal JPEG header

    def supports_content_hashing(self) -> bool:
        return False


@pytest.fixture
def dummy_storage_class() -> type:
    """Return the BaseDummyStorage class for customization in tests."""
    return BaseDummyStorage


@pytest.fixture
def dummy_storage() -> BaseDummyStorage:
    """Return a default BaseDummyStorage instance."""
    return BaseDummyStorage()


# ==============================================================================
# DUMMY AI FIXTURES (QC-001)
# ==============================================================================


class BaseDummyAnalyzer:
    """
    Base dummy vision analyzer for workflow tests.

    Centralizes the DummyAnalyzer pattern found across 7+ test files.
    """

    def __init__(
        self,
        analysis: ImageAnalysis | None = None,
        extended_fields: bool = False,
    ) -> None:
        if analysis:
            self._analysis = analysis
        elif extended_fields:
            self._analysis = ImageAnalysis(
                description="Fine-art portrait, soft light.",
                mood="calm",
                tags=["portrait", "softlight"],
                nsfw=False,
                safety_labels=[],
                subject="single subject, torso",
                style="fine-art",
                lighting="soft directional",
                camera="50mm",
                clothing_or_accessories="rope harness",
                aesthetic_terms=["minimalist", "graphic"],
                pose="upright",
                composition="center-weighted",
                background="plain backdrop",
                color_palette="black and white",
            )
        else:
            self._analysis = ImageAnalysis(
                description="Test image description",
                mood="neutral",
                tags=["test", "fixture"],
                nsfw=False,
                safety_labels=[],
            )

    async def analyze(self, url_or_bytes: str | bytes) -> tuple[ImageAnalysis, None]:
        return self._analysis, None


class BaseDummyGenerator:
    """
    Base dummy caption generator for workflow tests.

    Centralizes the DummyGenerator pattern found across 7+ test files.
    """

    def __init__(
        self,
        caption: str = "test caption #tags",
        sd_caption: str = "fine-art portrait, soft light, calm mood",
        config: OpenAIConfig | None = None,
    ) -> None:
        self._caption = caption
        self._sd_caption = sd_caption
        self.sd_caption_model = "gpt-4o-mini"
        if config:
            self.model = config.caption_model

    async def generate(self, analysis: ImageAnalysis, spec: CaptionSpec) -> tuple[str, None]:
        return self._caption, None

    async def generate_with_sd(self, analysis: ImageAnalysis, spec: CaptionSpec) -> tuple[dict[str, str], None]:
        return {"caption": self._caption, "sd_caption": self._sd_caption}, None


class BaseDummyAI:
    """
    Base dummy AIService for workflow tests.

    Centralizes the DummyAI pattern found across 4+ test files.
    """

    def __init__(
        self,
        analyzer: BaseDummyAnalyzer | None = None,
        generator: BaseDummyGenerator | None = None,
        caption: str = "hello world #tags",
    ) -> None:
        self._caption = caption
        self.analyzer = analyzer or BaseDummyAnalyzer()
        self.generator = generator or BaseDummyGenerator(caption=caption)

        # No-op rate limiter for AIService compatibility
        class _NoopLimiter:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

        self._rate_limiter = _NoopLimiter()

    async def create_caption_pair_from_analysis(
        self, analysis: ImageAnalysis, spec: CaptionSpec
    ) -> tuple[str, str, list]:
        return self._caption, self.generator._sd_caption, []

    async def create_multi_caption_pair_from_analysis(
        self, analysis: ImageAnalysis, specs: dict[str, CaptionSpec], **kwargs: object
    ) -> tuple[dict[str, str], str | None, list]:
        captions = {k: self._caption for k in specs}
        return captions, self.generator._sd_caption, []


@pytest.fixture
def dummy_analyzer_class() -> type:
    """Return the BaseDummyAnalyzer class for customization."""
    return BaseDummyAnalyzer


@pytest.fixture
def dummy_generator_class() -> type:
    """Return the BaseDummyGenerator class for customization."""
    return BaseDummyGenerator


@pytest.fixture
def dummy_ai_class() -> type:
    """Return the BaseDummyAI class for customization."""
    return BaseDummyAI


@pytest.fixture
def dummy_analyzer() -> BaseDummyAnalyzer:
    """Return a default BaseDummyAnalyzer instance."""
    return BaseDummyAnalyzer()


@pytest.fixture
def dummy_generator() -> BaseDummyGenerator:
    """Return a default BaseDummyGenerator instance."""
    return BaseDummyGenerator()


@pytest.fixture
def dummy_ai() -> BaseDummyAI:
    """Return a default BaseDummyAI instance."""
    return BaseDummyAI()


# ==============================================================================
# DUMMY PUBLISHER FIXTURES (QC-001)
# ==============================================================================


class BaseDummyPublisher:
    """
    Base dummy publisher for workflow tests.

    Centralizes the DummyPublisher pattern found across 5+ test files.
    """

    def __init__(
        self,
        platform: str = "dummy",
        enabled: bool = True,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        self._platform = platform
        self._enabled = enabled
        self._success = success
        self._error = error
        self.publish_calls: list[tuple[str, str]] = []  # Track (image_path, caption)

    @property
    def platform_name(self) -> str:
        return self._platform

    def is_enabled(self) -> bool:
        return self._enabled

    async def publish(self, image_path: str, caption: str, context: dict[str, Any] | None = None) -> PublishResult:
        self.publish_calls.append((image_path, caption))
        return PublishResult(
            success=self._success,
            platform=self._platform,
            error=self._error,
        )


@pytest.fixture
def dummy_publisher_class() -> type:
    """Return the BaseDummyPublisher class for customization."""
    return BaseDummyPublisher


@pytest.fixture
def dummy_publisher() -> BaseDummyPublisher:
    """Return a default BaseDummyPublisher instance."""
    return BaseDummyPublisher()


# ==============================================================================
# DUMMY DROPBOX CLIENT FIXTURES (QC-001)
# ==============================================================================


class BaseDummyClient:
    """
    Base dummy Dropbox client for low-level storage tests.

    Centralizes the DummyClient pattern found across 4+ test files.
    """

    def __init__(self, sidecar_exists: bool = True) -> None:
        self.created_dirs: list[str] = []
        self.moves: list[tuple[str, str]] = []
        self.uploads: list[tuple[str, bytes, Any]] = []
        self.sidecar_bytes: bytes | None = b"sidecar-content"
        self.sidecar_exists: bool = sidecar_exists

    def files_create_folder_v2(self, path: str) -> None:
        self.created_dirs.append(path)

    def files_move_v2(self, from_path: str, to_path: str, autorename: bool = False) -> None:
        from dropbox.exceptions import ApiError

        # Simulate sidecar missing by raising ApiError when appropriate.
        if from_path.endswith(".txt") and not self.sidecar_exists:

            class _Error:
                def is_path(self) -> bool:
                    return True

                def get_path(self) -> SimpleNamespace:
                    return SimpleNamespace(is_not_found=lambda: True)

            raise ApiError("req", _Error(), "not_found", "en-US")
        self.moves.append((from_path, to_path))

    def files_upload(
        self,
        data: bytes,
        path: str,
        mode: Any,
        mute: bool = False,
        strict_conflict: bool = False,
    ) -> None:
        self.uploads.append((path, data, mode))

    def files_download(self, path: str) -> tuple[None, SimpleNamespace]:
        from dropbox.exceptions import ApiError

        if not self.sidecar_exists:

            class _PathError:
                def is_not_found(self) -> bool:
                    return True

            class _Error:
                def is_path(self) -> bool:
                    return True

                def get_path(self) -> _PathError:
                    return _PathError()

            raise ApiError("request-id", _Error(), "not_found", "en-US")
        content = self.sidecar_bytes or b"sidecar-bytes"
        return None, SimpleNamespace(content=content)


@pytest.fixture
def dummy_client_class() -> type:
    """Return the BaseDummyClient class for customization."""
    return BaseDummyClient


@pytest.fixture
def dummy_client() -> BaseDummyClient:
    """Return a default BaseDummyClient instance."""
    return BaseDummyClient()


# ==============================================================================
# WORKFLOW BYPASS FIXTURES
# ==============================================================================


@pytest.fixture
def bypass_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass deduplication state for workflow tests."""
    monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
    monkeypatch.setattr("publisher_v2.core.workflow.save_posted_hash", lambda h: None)
