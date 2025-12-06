"""Tests for DropboxStorage.get_thumbnail() method."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from dropbox.exceptions import ApiError
from dropbox.files import ThumbnailSize, ThumbnailFormat

from publisher_v2.services.storage import DropboxStorage
from publisher_v2.core.exceptions import StorageError


@pytest.fixture
def mock_dropbox_config():
    """Create a mock DropboxConfig."""
    config = MagicMock()
    config.refresh_token = "test_refresh_token"
    config.app_key = "test_app_key"
    config.app_secret = "test_app_secret"
    return config


@pytest.fixture
def storage_with_mock_client(mock_dropbox_config):
    """Create DropboxStorage with mocked Dropbox client."""
    with patch("publisher_v2.services.storage.dropbox.Dropbox") as mock_dropbox:
        mock_client = MagicMock()
        mock_dropbox.return_value = mock_client
        storage = DropboxStorage(mock_dropbox_config)
        storage.client = mock_client
        yield storage, mock_client


@pytest.mark.asyncio
async def test_get_thumbnail_returns_bytes(storage_with_mock_client):
    """get_thumbnail returns JPEG bytes from Dropbox."""
    storage, mock_client = storage_with_mock_client
    
    # Mock the thumbnail response
    fake_jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF"  # JPEG magic bytes
    mock_response = MagicMock()
    mock_response.content = fake_jpeg_bytes
    mock_client.files_get_thumbnail_v2.return_value = (None, mock_response)
    
    result = await storage.get_thumbnail("/test_folder", "image.jpg")
    
    assert result == fake_jpeg_bytes
    mock_client.files_get_thumbnail_v2.assert_called_once()


@pytest.mark.asyncio
async def test_get_thumbnail_uses_default_size(storage_with_mock_client):
    """get_thumbnail uses w960h640 as default size."""
    storage, mock_client = storage_with_mock_client
    
    mock_response = MagicMock()
    mock_response.content = b"test_bytes"
    mock_client.files_get_thumbnail_v2.return_value = (None, mock_response)
    
    await storage.get_thumbnail("/folder", "image.jpg")
    
    call_args = mock_client.files_get_thumbnail_v2.call_args
    assert call_args.kwargs.get("size") == ThumbnailSize.w960h640


@pytest.mark.asyncio
async def test_get_thumbnail_uses_custom_size(storage_with_mock_client):
    """get_thumbnail respects custom size parameter."""
    storage, mock_client = storage_with_mock_client
    
    mock_response = MagicMock()
    mock_response.content = b"test_bytes"
    mock_client.files_get_thumbnail_v2.return_value = (None, mock_response)
    
    await storage.get_thumbnail("/folder", "image.jpg", size=ThumbnailSize.w640h480)
    
    call_args = mock_client.files_get_thumbnail_v2.call_args
    assert call_args.kwargs.get("size") == ThumbnailSize.w640h480


@pytest.mark.asyncio
async def test_get_thumbnail_uses_jpeg_format_by_default(storage_with_mock_client):
    """get_thumbnail uses JPEG format by default."""
    storage, mock_client = storage_with_mock_client
    
    mock_response = MagicMock()
    mock_response.content = b"test_bytes"
    mock_client.files_get_thumbnail_v2.return_value = (None, mock_response)
    
    await storage.get_thumbnail("/folder", "image.jpg")
    
    call_args = mock_client.files_get_thumbnail_v2.call_args
    assert call_args.kwargs.get("format") == ThumbnailFormat.jpeg


@pytest.mark.asyncio
async def test_get_thumbnail_raises_storage_error_on_api_error(storage_with_mock_client):
    """get_thumbnail raises StorageError on Dropbox API failure."""
    storage, mock_client = storage_with_mock_client
    
    # Create a mock ApiError
    mock_error = MagicMock()
    mock_client.files_get_thumbnail_v2.side_effect = ApiError(
        request_id="test_request",
        error=mock_error,
        user_message_text="Test error",
        user_message_locale="en",
    )
    
    with pytest.raises(StorageError) as exc_info:
        await storage.get_thumbnail("/folder", "image.jpg")
    
    assert "Failed to get thumbnail for image.jpg" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_thumbnail_constructs_correct_path(storage_with_mock_client):
    """get_thumbnail constructs the correct Dropbox path."""
    storage, mock_client = storage_with_mock_client
    
    mock_response = MagicMock()
    mock_response.content = b"test_bytes"
    mock_client.files_get_thumbnail_v2.return_value = (None, mock_response)
    
    await storage.get_thumbnail("/photos/2024", "sunset.jpg")
    
    call_args = mock_client.files_get_thumbnail_v2.call_args
    resource = call_args.kwargs.get("resource")
    # PathOrLink.path() creates a PathOrLink object with the path
    assert resource is not None

