"""
Tests for the CLI entrypoint (app.py).

This module tests:
- Command-line argument parsing
- Application initialization and wiring
- Preview mode vs. normal mode behavior
- Exit code handling
- Publisher initialization
"""

from __future__ import annotations

import argparse
import sys
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from publisher_v2.app import parse_args, main_async, main
from publisher_v2.core.models import ImageAnalysis, CaptionSpec


# ---------------------------------------------------------------------------
# Fixtures for mocking configuration and services
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_config():
    """Create a minimal mock application configuration."""
    dropbox = SimpleNamespace(
        app_key="test_key",
        app_secret="test_secret",
        refresh_token="test_token",
        image_folder="/Photos",
        archive_folder="/Archive",
    )
    openai = SimpleNamespace(
        api_key="sk-test",
        vision_model="gpt-4o",
        caption_model="gpt-4o",
    )
    platforms = SimpleNamespace(
        telegram_enabled=False,
        instagram_enabled=False,
        email_enabled=False,
    )
    features = SimpleNamespace(
        analyze_caption_enabled=True,
        publish_enabled=True,
        keep_enabled=True,
        remove_enabled=True,
        auto_view_enabled=False,
    )
    content = SimpleNamespace(
        hashtag_string="#test",
        archive=True,
        debug=False,
    )
    captionfile = SimpleNamespace(
        enabled=False,
        extended_metadata_enabled=False,
        artist_alias=None,
    )
    email = SimpleNamespace(
        subject_mode="normal",
        caption_target="subject",
        confirmation_to_sender=True,
        confirmation_tags_count=5,
        confirmation_tags_nature="neutral",
    )
    return SimpleNamespace(
        dropbox=dropbox,
        openai=openai,
        platforms=platforms,
        features=features,
        content=content,
        captionfile=captionfile,
        telegram=None,
        instagram=None,
        email=email,
    )


@pytest.fixture
def mock_workflow_result():
    """Create a successful workflow result."""
    return SimpleNamespace(
        success=True,
        image_name="test_image.jpg",
        image_folder="/Photos",
        sha256="abc123",
        dropbox_url="https://dropbox.com/test",
        caption="Test caption #test",
        caption_spec=CaptionSpec(
            platform="generic",
            style="casual",
            hashtags="#test",
            max_length=280,
        ),
        image_analysis=ImageAnalysis(
            description="A test image",
            mood="neutral",
            tags=["test", "sample"],
            nsfw=False,
            safety_labels=[],
        ),
        archived=False,
        correlation_id="test-123",
        publish_results={},
        error=None,
    )


@pytest.fixture
def mock_failed_result():
    """Create a failed workflow result."""
    return SimpleNamespace(
        success=False,
        image_name=None,
        image_folder=None,
        sha256=None,
        dropbox_url=None,
        caption=None,
        caption_spec=None,
        image_analysis=None,
        archived=False,
        correlation_id=None,
        publish_results={},
        error="No images found",
    )


@pytest.fixture
def mock_services(monkeypatch: pytest.MonkeyPatch, mock_config):
    """
    Set up all the service mocks needed for main_async tests.
    
    Returns a dict with references to the mocks for assertions.
    """
    mocks = {
        "storage": MagicMock(),
        "analyzer": MagicMock(),
        "generator": MagicMock(),
        "ai_service": MagicMock(),
        "telegram": MagicMock(),
        "email": MagicMock(),
        "instagram": MagicMock(),
        "orchestrator": MagicMock(),
    }
    
    # Set model attribute on generator for preview mode
    mocks["generator"].model = "gpt-4o"
    mocks["analyzer"].model = "gpt-4o"
    
    # Set storage get_file_metadata for preview mode
    mocks["storage"].get_file_metadata = AsyncMock(return_value={"id": "abc", "rev": "1"})
    
    # Set is_enabled for publishers
    mocks["telegram"].is_enabled.return_value = False
    mocks["telegram"].platform_name = "telegram"
    mocks["email"].is_enabled.return_value = False
    mocks["email"].platform_name = "email"
    mocks["instagram"].is_enabled.return_value = False
    mocks["instagram"].platform_name = "instagram"
    
    monkeypatch.setattr("publisher_v2.app.load_application_config", lambda *a: mock_config)
    monkeypatch.setattr("publisher_v2.app.DropboxStorage", lambda cfg: mocks["storage"])
    monkeypatch.setattr("publisher_v2.app.VisionAnalyzerOpenAI", lambda cfg: mocks["analyzer"])
    monkeypatch.setattr("publisher_v2.app.CaptionGeneratorOpenAI", lambda cfg: mocks["generator"])
    monkeypatch.setattr("publisher_v2.app.AIService", lambda analyzer, generator: mocks["ai_service"])
    monkeypatch.setattr("publisher_v2.app.TelegramPublisher", lambda cfg, enabled: mocks["telegram"])
    monkeypatch.setattr("publisher_v2.app.EmailPublisher", lambda cfg, enabled: mocks["email"])
    monkeypatch.setattr("publisher_v2.app.InstagramPublisher", lambda cfg, enabled: mocks["instagram"])
    monkeypatch.setattr("publisher_v2.app.WorkflowOrchestrator", lambda *a: mocks["orchestrator"])
    
    return mocks


# ---------------------------------------------------------------------------
# Tests for parse_args()
# ---------------------------------------------------------------------------

class TestParseArgs:
    """Tests for CLI argument parsing."""

    def test_parse_args_config_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Config argument is required."""
        monkeypatch.setattr(sys, "argv", ["app.py"])
        with pytest.raises(SystemExit):
            parse_args()

    def test_parse_args_config_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Basic invocation with only config."""
        monkeypatch.setattr(sys, "argv", ["app.py", "--config", "test.ini"])
        args = parse_args()
        assert args.config == "test.ini"
        assert args.env is None
        assert args.debug is False
        assert args.select is None
        assert args.dry_publish is False
        assert args.preview is False

    def test_parse_args_with_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Parsing with --env option."""
        monkeypatch.setattr(sys, "argv", ["app.py", "--config", "test.ini", "--env", ".env"])
        args = parse_args()
        assert args.config == "test.ini"
        assert args.env == ".env"

    def test_parse_args_debug_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Parsing with --debug flag."""
        monkeypatch.setattr(sys, "argv", ["app.py", "--config", "test.ini", "--debug"])
        args = parse_args()
        assert args.debug is True

    def test_parse_args_select_option(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Parsing with --select option."""
        monkeypatch.setattr(sys, "argv", ["app.py", "--config", "test.ini", "--select", "image.jpg"])
        args = parse_args()
        assert args.select == "image.jpg"

    def test_parse_args_dry_publish_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Parsing with --dry-publish flag."""
        monkeypatch.setattr(sys, "argv", ["app.py", "--config", "test.ini", "--dry-publish"])
        args = parse_args()
        assert args.dry_publish is True

    def test_parse_args_preview_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Parsing with --preview flag."""
        monkeypatch.setattr(sys, "argv", ["app.py", "--config", "test.ini", "--preview"])
        args = parse_args()
        assert args.preview is True

    def test_parse_args_all_options(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Parsing with all options combined."""
        monkeypatch.setattr(sys, "argv", [
            "app.py",
            "--config", "test.ini",
            "--env", ".env",
            "--debug",
            "--select", "specific.jpg",
            "--dry-publish",
            "--preview",
        ])
        args = parse_args()
        assert args.config == "test.ini"
        assert args.env == ".env"
        assert args.debug is True
        assert args.select == "specific.jpg"
        assert args.dry_publish is True
        assert args.preview is True


# ---------------------------------------------------------------------------
# Tests for main_async() - Normal mode
# ---------------------------------------------------------------------------

class TestMainAsyncNormalMode:
    """Tests for main_async() in normal (non-preview) mode."""

    @pytest.mark.asyncio
    async def test_main_async_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_services,
        mock_workflow_result,
    ) -> None:
        """Successful execution returns exit code 0."""
        monkeypatch.setattr(sys, "argv", ["app.py", "--config", "test.ini"])
        mock_services["orchestrator"].execute = AsyncMock(return_value=mock_workflow_result)
        
        exit_code = await main_async()
        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_main_async_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_services,
        mock_failed_result,
    ) -> None:
        """Failed execution returns exit code 1."""
        monkeypatch.setattr(sys, "argv", ["app.py", "--config", "test.ini"])
        mock_services["orchestrator"].execute = AsyncMock(return_value=mock_failed_result)
        
        exit_code = await main_async()
        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_main_async_debug_flag_sets_config(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_config,
        mock_workflow_result,
    ) -> None:
        """--debug flag sets config.content.debug to True."""
        monkeypatch.setattr(sys, "argv", ["app.py", "--config", "test.ini", "--debug"])
        
        captured_config = None
        
        def capture_config(config, storage, ai, publishers):
            nonlocal captured_config
            captured_config = config
            mock = MagicMock()
            mock.execute = AsyncMock(return_value=mock_workflow_result)
            return mock
        
        monkeypatch.setattr("publisher_v2.app.load_application_config", lambda *a: mock_config)
        monkeypatch.setattr("publisher_v2.app.DropboxStorage", lambda cfg: MagicMock())
        monkeypatch.setattr("publisher_v2.app.VisionAnalyzerOpenAI", lambda cfg: MagicMock())
        monkeypatch.setattr("publisher_v2.app.CaptionGeneratorOpenAI", lambda cfg: MagicMock())
        monkeypatch.setattr("publisher_v2.app.AIService", lambda a, g: MagicMock())
        monkeypatch.setattr("publisher_v2.app.TelegramPublisher", lambda c, e: MagicMock())
        monkeypatch.setattr("publisher_v2.app.EmailPublisher", lambda c, e: MagicMock())
        monkeypatch.setattr("publisher_v2.app.InstagramPublisher", lambda c, e: MagicMock())
        monkeypatch.setattr("publisher_v2.app.WorkflowOrchestrator", capture_config)
        
        await main_async()
        
        assert captured_config.content.debug is True

    @pytest.mark.asyncio
    async def test_main_async_passes_select_to_orchestrator(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_services,
        mock_workflow_result,
    ) -> None:
        """--select option is passed to orchestrator.execute()."""
        monkeypatch.setattr(sys, "argv", ["app.py", "--config", "test.ini", "--select", "specific.jpg"])
        
        mock_execute = AsyncMock(return_value=mock_workflow_result)
        mock_services["orchestrator"].execute = mock_execute
        
        await main_async()
        
        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args.kwargs
        assert call_kwargs["select_filename"] == "specific.jpg"

    @pytest.mark.asyncio
    async def test_main_async_dry_publish_flag(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_services,
        mock_workflow_result,
    ) -> None:
        """--dry-publish flag is passed to orchestrator.execute()."""
        monkeypatch.setattr(sys, "argv", ["app.py", "--config", "test.ini", "--dry-publish"])
        
        mock_execute = AsyncMock(return_value=mock_workflow_result)
        mock_services["orchestrator"].execute = mock_execute
        
        await main_async()
        
        call_kwargs = mock_execute.call_args.kwargs
        assert call_kwargs["dry_publish"] is True


# ---------------------------------------------------------------------------
# Tests for main_async() - Preview mode
# ---------------------------------------------------------------------------

class TestMainAsyncPreviewMode:
    """Tests for main_async() in preview mode."""

    @pytest.mark.asyncio
    async def test_preview_mode_success_returns_0(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_services,
        mock_workflow_result,
    ) -> None:
        """Preview mode with successful result returns 0."""
        monkeypatch.setattr(sys, "argv", ["app.py", "--config", "test.ini", "--preview"])
        mock_services["orchestrator"].execute = AsyncMock(return_value=mock_workflow_result)
        
        # Mock preview utilities to avoid output
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_preview_header", lambda: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_config_summary", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_image_details", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_vision_analysis", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_caption", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_platform_preview", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_preview_footer", lambda: None)
        
        exit_code = await main_async()
        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_preview_mode_failure_returns_1(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_services,
        mock_failed_result,
    ) -> None:
        """Preview mode with failed result returns 1."""
        monkeypatch.setattr(sys, "argv", ["app.py", "--config", "test.ini", "--preview"])
        mock_services["orchestrator"].execute = AsyncMock(return_value=mock_failed_result)
        
        # Mock preview utilities
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_preview_header", lambda: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_config_summary", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_error", lambda e: None)
        
        exit_code = await main_async()
        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_preview_mode_sets_dry_publish(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_services,
        mock_workflow_result,
    ) -> None:
        """Preview mode implies dry_publish=True."""
        monkeypatch.setattr(sys, "argv", ["app.py", "--config", "test.ini", "--preview"])
        
        mock_execute = AsyncMock(return_value=mock_workflow_result)
        mock_services["orchestrator"].execute = mock_execute
        
        # Mock preview utilities
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_preview_header", lambda: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_config_summary", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_image_details", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_vision_analysis", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_caption", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_platform_preview", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_preview_footer", lambda: None)
        
        await main_async()
        
        call_kwargs = mock_execute.call_args.kwargs
        assert call_kwargs["dry_publish"] is True
        assert call_kwargs["preview_mode"] is True


# ---------------------------------------------------------------------------
# Tests for main_async() - Publisher initialization
# ---------------------------------------------------------------------------

class TestPublisherInitialization:
    """Tests for publisher initialization based on config."""

    @pytest.mark.asyncio
    async def test_publishers_created_with_config(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_config,
        mock_workflow_result,
    ) -> None:
        """Publishers are created with correct config and enabled status."""
        monkeypatch.setattr(sys, "argv", ["app.py", "--config", "test.ini"])
        
        telegram_calls = []
        email_calls = []
        instagram_calls = []
        
        def track_telegram(*args):
            telegram_calls.append(args)
            return MagicMock()
        
        def track_email(*args):
            email_calls.append(args)
            return MagicMock()
        
        def track_instagram(*args):
            instagram_calls.append(args)
            return MagicMock()
        
        mock_orchestrator = MagicMock()
        mock_orchestrator.execute = AsyncMock(return_value=mock_workflow_result)
        
        monkeypatch.setattr("publisher_v2.app.load_application_config", lambda *a: mock_config)
        monkeypatch.setattr("publisher_v2.app.DropboxStorage", lambda cfg: MagicMock())
        monkeypatch.setattr("publisher_v2.app.VisionAnalyzerOpenAI", lambda cfg: MagicMock())
        monkeypatch.setattr("publisher_v2.app.CaptionGeneratorOpenAI", lambda cfg: MagicMock())
        monkeypatch.setattr("publisher_v2.app.AIService", lambda a, g: MagicMock())
        monkeypatch.setattr("publisher_v2.app.TelegramPublisher", track_telegram)
        monkeypatch.setattr("publisher_v2.app.EmailPublisher", track_email)
        monkeypatch.setattr("publisher_v2.app.InstagramPublisher", track_instagram)
        monkeypatch.setattr("publisher_v2.app.WorkflowOrchestrator", lambda *a: mock_orchestrator)
        
        await main_async()
        
        # Check Telegram publisher was created
        assert len(telegram_calls) == 1
        assert telegram_calls[0][0] is None  # telegram config is None
        assert telegram_calls[0][1] is False  # telegram_enabled is False
        
        # Check Email publisher was created
        assert len(email_calls) == 1
        assert email_calls[0][1] is False  # email_enabled is False
        
        # Check Instagram publisher was created
        assert len(instagram_calls) == 1
        assert instagram_calls[0][0] is None  # instagram config is None
        assert instagram_calls[0][1] is False  # instagram_enabled is False


# ---------------------------------------------------------------------------
# Tests for main() - Sync entrypoint
# ---------------------------------------------------------------------------

class TestMainSync:
    """Tests for the synchronous main() entrypoint."""

    def test_main_raises_system_exit_on_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """main() raises SystemExit with code 0 on success."""
        async def mock_main_async():
            return 0
        
        monkeypatch.setattr("publisher_v2.app.main_async", mock_main_async)
        
        with pytest.raises(SystemExit) as exc_info:
            main()
        
        assert exc_info.value.code == 0

    def test_main_raises_system_exit_on_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """main() raises SystemExit with code 1 on failure."""
        async def mock_main_async():
            return 1
        
        monkeypatch.setattr("publisher_v2.app.main_async", mock_main_async)
        
        with pytest.raises(SystemExit) as exc_info:
            main()
        
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Tests for email preview path
# ---------------------------------------------------------------------------

class TestEmailPreviewPath:
    """Tests for email confirmation preview in preview mode."""

    @pytest.mark.asyncio
    async def test_preview_mode_with_email_enabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_config,
        mock_workflow_result,
    ) -> None:
        """Preview mode shows email confirmation preview when email is enabled."""
        # Enable email
        mock_config.platforms.email_enabled = True
        
        monkeypatch.setattr(sys, "argv", ["app.py", "--config", "test.ini", "--preview"])
        
        mock_execute = AsyncMock(return_value=mock_workflow_result)
        mock_orchestrator = MagicMock()
        mock_orchestrator.execute = mock_execute
        
        mock_storage = MagicMock()
        mock_storage.get_file_metadata = AsyncMock(return_value={"id": "abc", "rev": "1"})
        
        email_preview_called = []
        
        def track_email_preview(**kwargs):
            email_preview_called.append(kwargs)
        
        monkeypatch.setattr("publisher_v2.app.load_application_config", lambda *a: mock_config)
        monkeypatch.setattr("publisher_v2.app.DropboxStorage", lambda cfg: mock_storage)
        monkeypatch.setattr("publisher_v2.app.VisionAnalyzerOpenAI", lambda cfg: MagicMock())
        monkeypatch.setattr("publisher_v2.app.CaptionGeneratorOpenAI", lambda cfg: MagicMock())
        monkeypatch.setattr("publisher_v2.app.AIService", lambda a, g: MagicMock())
        
        # Create mock publishers with is_enabled returning proper values
        mock_telegram = MagicMock()
        mock_telegram.is_enabled.return_value = False
        mock_telegram.platform_name = "telegram"
        
        mock_email_pub = MagicMock()
        mock_email_pub.is_enabled.return_value = True
        mock_email_pub.platform_name = "email"
        
        mock_instagram = MagicMock()
        mock_instagram.is_enabled.return_value = False
        mock_instagram.platform_name = "instagram"
        
        monkeypatch.setattr("publisher_v2.app.TelegramPublisher", lambda *a: mock_telegram)
        monkeypatch.setattr("publisher_v2.app.EmailPublisher", lambda *a: mock_email_pub)
        monkeypatch.setattr("publisher_v2.app.InstagramPublisher", lambda *a: mock_instagram)
        monkeypatch.setattr("publisher_v2.app.WorkflowOrchestrator", lambda *a: mock_orchestrator)
        
        # Mock preview utilities
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_preview_header", lambda: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_config_summary", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_image_details", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_vision_analysis", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_caption", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_platform_preview", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_email_confirmation_preview", track_email_preview)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_preview_footer", lambda: None)
        
        await main_async()
        
        # Verify email confirmation preview was called
        assert len(email_preview_called) == 1
        assert email_preview_called[0]["enabled"] is True


# ---------------------------------------------------------------------------
# Tests for SD caption preview path
# ---------------------------------------------------------------------------

class TestSDCaptionPreviewPath:
    """Tests for SD caption sidecar preview in preview mode."""

    @pytest.mark.asyncio
    async def test_preview_mode_with_sd_caption(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_config,
    ) -> None:
        """Preview mode shows SD caption sidecar preview when sd_caption is present."""
        # Create result with sd_caption
        mock_analysis = ImageAnalysis(
            description="A test image",
            mood="neutral",
            tags=["test"],
            nsfw=False,
            safety_labels=[],
        )
        # Add sd_caption attribute dynamically
        object.__setattr__(mock_analysis, "sd_caption", "beautiful photograph, natural lighting")
        
        mock_result = SimpleNamespace(
            success=True,
            image_name="test.jpg",
            image_folder="/Photos",
            sha256="abc123",
            dropbox_url="https://example.com",
            caption="Test caption",
            caption_spec=CaptionSpec(
                platform="generic",
                style="casual",
                hashtags="#test",
                max_length=280,
            ),
            image_analysis=mock_analysis,
            archived=False,
            correlation_id="test-123",
            publish_results={},
            error=None,
        )
        
        monkeypatch.setattr(sys, "argv", ["app.py", "--config", "test.ini", "--preview"])
        
        mock_execute = AsyncMock(return_value=mock_result)
        mock_orchestrator = MagicMock()
        mock_orchestrator.execute = mock_execute
        
        mock_storage = MagicMock()
        mock_storage.get_file_metadata = AsyncMock(return_value={"id": "abc", "rev": "1"})
        
        mock_generator = MagicMock()
        mock_generator.model = "gpt-4o"
        
        sidecar_preview_called = []
        
        def track_sidecar_preview(sd_caption, metadata):
            sidecar_preview_called.append((sd_caption, metadata))
        
        monkeypatch.setattr("publisher_v2.app.load_application_config", lambda *a: mock_config)
        monkeypatch.setattr("publisher_v2.app.DropboxStorage", lambda cfg: mock_storage)
        monkeypatch.setattr("publisher_v2.app.VisionAnalyzerOpenAI", lambda cfg: MagicMock())
        monkeypatch.setattr("publisher_v2.app.CaptionGeneratorOpenAI", lambda cfg: mock_generator)
        monkeypatch.setattr("publisher_v2.app.AIService", lambda a, g: MagicMock())
        monkeypatch.setattr("publisher_v2.app.TelegramPublisher", lambda c, e: MagicMock())
        monkeypatch.setattr("publisher_v2.app.EmailPublisher", lambda c, e: MagicMock())
        monkeypatch.setattr("publisher_v2.app.InstagramPublisher", lambda c, e: MagicMock())
        monkeypatch.setattr("publisher_v2.app.WorkflowOrchestrator", lambda *a: mock_orchestrator)
        
        # Mock preview utilities
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_preview_header", lambda: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_config_summary", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_image_details", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_vision_analysis", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_caption", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_caption_sidecar_preview", track_sidecar_preview)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_platform_preview", lambda **k: None)
        monkeypatch.setattr("publisher_v2.app.preview_utils.print_preview_footer", lambda: None)
        
        await main_async()
        
        # Verify sidecar preview was called with sd_caption
        assert len(sidecar_preview_called) == 1
        assert sidecar_preview_called[0][0] == "beautiful photograph, natural lighting"

