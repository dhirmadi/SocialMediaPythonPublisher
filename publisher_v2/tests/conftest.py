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
from typing import Generator, List, Optional, Tuple, Any, Dict
from types import SimpleNamespace

import pytest

from publisher_v2.config.schema import (
    DropboxConfig,
    OpenAIConfig,
    ApplicationConfig,
    ContentConfig,
    PlatformsConfig,
    CaptionFileConfig,
)
from publisher_v2.core.models import ImageAnalysis, CaptionSpec, PublishResult


# ==============================================================================
# ENVIRONMENT ISOLATION FIXTURES
# ==============================================================================


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
        "web_admin_pw",
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
        config: Optional[DropboxConfig] = None,
        images: Optional[List[str]] = None,
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
        self.sidecar_text: Optional[str] = None
        self.sidecars_written: int = 0
        self.archives: int = 0
        self.moves: List[Tuple[str, str, str]] = []  # (folder, filename, target)

    async def list_images(self, folder: str) -> List[str]:
        return self._images

    async def download_image(self, folder: str, filename: str) -> bytes:
        return self._content

    async def get_temporary_link(self, folder: str, filename: str) -> str:
        return f"https://example.com/tmp/{filename}"

    async def get_file_metadata(self, folder: str, filename: str) -> Dict[str, str]:
        return {"id": "id:XYZ", "rev": "123"}

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        self.sidecar_text = text
        self.sidecars_written += 1

    async def download_sidecar_if_exists(self, folder: str, filename: str) -> Optional[bytes]:
        return None  # Default: no sidecar

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        self.archives += 1

    async def move_image_with_sidecars(self, folder: str, filename: str, target: str) -> None:
        self.moves.append((folder, filename, target))


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
        analysis: Optional[ImageAnalysis] = None,
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

    async def analyze(self, url_or_bytes: str | bytes) -> ImageAnalysis:
        return self._analysis


class BaseDummyGenerator:
    """
    Base dummy caption generator for workflow tests.
    
    Centralizes the DummyGenerator pattern found across 7+ test files.
    """
    
    def __init__(
        self,
        caption: str = "test caption #tags",
        sd_caption: str = "fine-art portrait, soft light, calm mood",
        config: Optional[OpenAIConfig] = None,
    ) -> None:
        self._caption = caption
        self._sd_caption = sd_caption
        self.sd_caption_model = "gpt-4o-mini"
        if config:
            self.model = config.caption_model

    async def generate(self, analysis: ImageAnalysis, spec: CaptionSpec) -> str:
        return self._caption

    async def generate_with_sd(
        self, analysis: ImageAnalysis, spec: CaptionSpec
    ) -> Dict[str, str]:
        return {"caption": self._caption, "sd_caption": self._sd_caption}


class BaseDummyAI:
    """
    Base dummy AIService for workflow tests.
    
    Centralizes the DummyAI pattern found across 4+ test files.
    """
    
    def __init__(
        self,
        analyzer: Optional[BaseDummyAnalyzer] = None,
        generator: Optional[BaseDummyGenerator] = None,
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

    async def create_caption(self, url_or_bytes: str | bytes, spec: CaptionSpec) -> str:
        return self._caption

    async def create_caption_pair(
        self, url_or_bytes: str | bytes, spec: CaptionSpec
    ) -> Tuple[str, str]:
        return self._caption, self.generator._sd_caption

    async def create_caption_pair_from_analysis(
        self, analysis: ImageAnalysis, spec: CaptionSpec
    ) -> Tuple[str, str]:
        return self._caption, self.generator._sd_caption


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
        error: Optional[str] = None,
    ) -> None:
        self._platform = platform
        self._enabled = enabled
        self._success = success
        self._error = error
        self.publish_calls: List[Tuple[str, str]] = []  # Track (image_path, caption)

    @property
    def platform_name(self) -> str:
        return self._platform

    def is_enabled(self) -> bool:
        return self._enabled

    async def publish(
        self, image_path: str, caption: str, context: Optional[Dict[str, Any]] = None
    ) -> PublishResult:
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
        self.created_dirs: List[str] = []
        self.moves: List[Tuple[str, str]] = []
        self.uploads: List[Tuple[str, bytes, Any]] = []
        self.sidecar_bytes: Optional[bytes] = b"sidecar-content"
        self.sidecar_exists: bool = sidecar_exists

    def files_create_folder_v2(self, path: str) -> None:
        self.created_dirs.append(path)

    def files_move_v2(
        self, from_path: str, to_path: str, autorename: bool = False
    ) -> None:
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

    def files_download(self, path: str) -> Tuple[None, SimpleNamespace]:
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

