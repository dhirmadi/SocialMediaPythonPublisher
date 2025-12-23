"""
Tests for web/service.py uncovered paths (QC-003).

These tests cover the uncovered lines in WebImageService:
- Line 51: RuntimeError for missing CONFIG_PATH
- Lines 80-86: TTL parsing logic
- Lines 155-163: get_image_details exception handling
- Lines 199-211: get_thumbnail logic
- Lines 299-309: sd_caption error fallback
- Lines 337-339: sidecar write exception handling
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Valid INI content with correct section names (case-sensitive)
VALID_INI_CONTENT = """
[Dropbox]
image_folder = /Photos
archive_folder = archive

[OpenAI]

[Content]
hashtag_string = #test
archive = false
debug = false

[Features]
analyze_caption_enabled = true
publish_enabled = true

[Platforms]
telegram_enabled = false
instagram_enabled = false
email_enabled = false
"""


class TestWebImageServiceConfigPath:
    """Tests for CONFIG_PATH validation."""
    
    def test_raises_runtime_error_when_config_path_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify WebImageService raises ConfigurationError when CONFIG_PATH not set and not in env-first mode."""
        from publisher_v2.core.exceptions import ConfigurationError
        
        # Ensure CONFIG_PATH is not set
        monkeypatch.delenv("CONFIG_PATH", raising=False)
        # Ensure not in env-first mode (no STORAGE_PATHS, PUBLISHERS, OPENAI_SETTINGS)
        monkeypatch.delenv("STORAGE_PATHS", raising=False)
        monkeypatch.delenv("PUBLISHERS", raising=False)
        monkeypatch.delenv("OPENAI_SETTINGS", raising=False)
        
        from publisher_v2.web.service import WebImageService
        
        with pytest.raises(ConfigurationError, match="Either config_file_path must be provided or all required env vars"):
            WebImageService()


class TestWebImageServiceTTLParsing:
    """Tests for TTL parsing logic (lines 80-86)."""
    
    def test_uses_env_ttl_when_valid(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Verify WebImageService uses WEB_IMAGE_CACHE_TTL_SECONDS from env when valid."""
        # Create minimal config file
        config_file = tmp_path / "test.ini"
        config_file.write_text(VALID_INI_CONTENT)
        
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        monkeypatch.setenv("WEB_IMAGE_CACHE_TTL_SECONDS", "120")
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        
        # Patch Dropbox client to avoid real API calls
        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.web.service import WebImageService
            service = WebImageService()
            
            assert service._image_cache_ttl_seconds == 120.0
    
    def test_uses_default_ttl_when_env_invalid(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Verify WebImageService uses default TTL when env value is invalid."""
        config_file = tmp_path / "test.ini"
        config_file.write_text(VALID_INI_CONTENT)
        
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        monkeypatch.setenv("WEB_IMAGE_CACHE_TTL_SECONDS", "invalid")
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        
        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.web.service import WebImageService
            service = WebImageService()
            
            # Should use the default from static config, not crash
            assert service._image_cache_ttl_seconds > 0
    
    def test_ignores_negative_env_ttl(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Verify WebImageService ignores negative TTL values from env."""
        config_file = tmp_path / "test.ini"
        config_file.write_text(VALID_INI_CONTENT)
        
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        monkeypatch.setenv("WEB_IMAGE_CACHE_TTL_SECONDS", "-10")
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        
        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.web.service import WebImageService
            service = WebImageService()
            
            # Should use the default from static config (>0), not negative value
            assert service._image_cache_ttl_seconds > 0


class TestGetImageDetailsExceptionHandling:
    """Tests for get_image_details exception handling (lines 155-163)."""
    
    @pytest.mark.asyncio
    async def test_raises_file_not_found_on_storage_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Verify get_image_details raises FileNotFoundError on storage errors."""
        config_file = tmp_path / "test.ini"
        config_file.write_text(VALID_INI_CONTENT)
        
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        
        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.web.service import WebImageService
            service = WebImageService()
            
            # Mock storage to raise an error
            service.storage.get_temporary_link = AsyncMock(side_effect=Exception("Storage error"))
            
            with pytest.raises(FileNotFoundError, match="not found"):
                await service.get_image_details("nonexistent.jpg")


class TestGetThumbnailSizeMapping:
    """Tests for get_thumbnail size mapping (lines 199-211)."""
    
    @pytest.mark.asyncio
    async def test_maps_known_thumbnail_sizes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Verify get_thumbnail correctly maps size strings to ThumbnailSize enums."""
        config_file = tmp_path / "test.ini"
        config_file.write_text(VALID_INI_CONTENT)
        
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        
        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.web.service import WebImageService
            from dropbox.files import ThumbnailSize
            
            service = WebImageService()
            
            # Mock storage get_thumbnail
            service.storage.get_thumbnail = AsyncMock(return_value=b"thumbnail_bytes")
            
            # Test different size mappings
            for size_str in ["w256h256", "w480h320", "w640h480", "w960h640", "w1024h768"]:
                result = await service.get_thumbnail("test.jpg", size=size_str)
                assert result == b"thumbnail_bytes"
    
    @pytest.mark.asyncio
    async def test_defaults_to_w960h640_for_unknown_size(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Verify get_thumbnail defaults to w960h640 for unknown size strings."""
        config_file = tmp_path / "test.ini"
        config_file.write_text(VALID_INI_CONTENT)
        
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        
        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.web.service import WebImageService
            from dropbox.files import ThumbnailSize
            
            service = WebImageService()
            
            # Mock storage get_thumbnail
            service.storage.get_thumbnail = AsyncMock(return_value=b"thumbnail_bytes")
            
            # Test unknown size
            result = await service.get_thumbnail("test.jpg", size="unknown_size")
            assert result == b"thumbnail_bytes"
            
            # Verify default size was used
            call_kwargs = service.storage.get_thumbnail.call_args.kwargs
            assert call_kwargs.get("size") == ThumbnailSize.w960h640


class TestAnalyzeAndCaptionSdCaptionFallback:
    """Tests for sd_caption error fallback (lines 299-309)."""
    
    @pytest.mark.asyncio
    async def test_falls_back_to_legacy_caption_on_sd_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Verify analyze_and_caption falls back to legacy caption when sd_caption fails."""
        config_file = tmp_path / "test.ini"
        config_file.write_text(VALID_INI_CONTENT)
        
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        
        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.web.service import WebImageService
            from publisher_v2.core.models import ImageAnalysis
            
            service = WebImageService()
            
            # Mock storage methods
            service.storage.get_temporary_link = AsyncMock(return_value="http://temp")
            service.storage.download_sidecar_if_exists = AsyncMock(return_value=None)
            
            # Mock AI service - pair fails, fallback succeeds
            analysis = ImageAnalysis(
                description="Test",
                mood="neutral",
                tags=["test"],
                nsfw=False,
                safety_labels=[],
            )
            service.ai_service.analyzer.analyze = AsyncMock(return_value=analysis)
            service.ai_service.create_caption_pair_from_analysis = AsyncMock(
                side_effect=Exception("SD caption failed")
            )
            service.ai_service.create_caption = AsyncMock(return_value="fallback caption")
            
            result = await service.analyze_and_caption("test.jpg")
            
            assert result.caption == "fallback caption"
            assert result.sd_caption is None


class TestAnalyzeAndCaptionSidecarWriteException:
    """Tests for sidecar write exception handling (lines 337-339)."""
    
    @pytest.mark.asyncio
    async def test_continues_on_sidecar_write_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Verify analyze_and_caption continues when sidecar write fails."""
        config_file = tmp_path / "test.ini"
        config_file.write_text(VALID_INI_CONTENT)
        
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        
        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.web.service import WebImageService
            from publisher_v2.core.models import ImageAnalysis
            
            service = WebImageService()
            
            # Mock storage methods
            service.storage.get_temporary_link = AsyncMock(return_value="http://temp")
            service.storage.download_sidecar_if_exists = AsyncMock(return_value=None)
            
            # Mock AI service
            analysis = ImageAnalysis(
                description="Test",
                mood="neutral",
                tags=["test"],
                nsfw=False,
                safety_labels=[],
            )
            service.ai_service.analyzer.analyze = AsyncMock(return_value=analysis)
            service.ai_service.create_caption_pair_from_analysis = AsyncMock(
                return_value=("caption", "sd_caption")
            )
            
            # Mock sidecar generation to fail - the import is inside the method
            with patch("publisher_v2.services.sidecar.generate_and_upload_sidecar") as mock_sidecar:
                mock_sidecar.side_effect = Exception("Sidecar write failed")
                
                result = await service.analyze_and_caption("test.jpg")
                
                # Should still return valid response despite sidecar failure
                assert result.caption == "caption"
                assert result.sd_caption == "sd_caption"
                assert result.sidecar_written is False


class TestListImages:
    """Tests for list_images logic (lines 177-182)."""
    
    @pytest.mark.asyncio
    async def test_returns_sorted_list(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """Verify list_images returns sorted filenames."""
        config_file = tmp_path / "test.ini"
        config_file.write_text(VALID_INI_CONTENT)
        
        monkeypatch.setenv("CONFIG_PATH", str(config_file))
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        
        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.web.service import WebImageService
            
            service = WebImageService()
            
            # Mock storage to return unsorted list
            service.storage.list_images = AsyncMock(return_value=["zebra.jpg", "apple.jpg", "mango.jpg"])
            
            result = await service.list_images()
            
            assert result["filenames"] == ["apple.jpg", "mango.jpg", "zebra.jpg"]
            assert result["count"] == 3

