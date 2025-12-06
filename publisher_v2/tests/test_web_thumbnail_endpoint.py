"""Tests for /api/images/{filename}/thumbnail endpoint."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient

from publisher_v2.core.exceptions import StorageError
from publisher_v2.web.app import app, get_service


class MockWebImageService:
    """Mock WebImageService for testing."""
    
    def __init__(self, auto_view_enabled: bool = True):
        self.config = MagicMock()
        self.config.features = MagicMock()
        self.config.features.auto_view_enabled = auto_view_enabled
        self._thumbnail_bytes = b"\xff\xd8\xff\xe0JFIF"
        self._error = None
    
    async def get_thumbnail(self, filename: str, size: str = "w960h640") -> bytes:
        if self._error:
            raise self._error
        return self._thumbnail_bytes


@pytest.fixture
def mock_service():
    """Create a mock service with auto_view enabled."""
    return MockWebImageService(auto_view_enabled=True)


@pytest.fixture
def client_with_mock(mock_service):
    """Create test client with mocked service."""
    # Override the get_service dependency
    app.dependency_overrides[get_service] = lambda: mock_service
    yield TestClient(app), mock_service
    # Clean up
    app.dependency_overrides.clear()


def test_thumbnail_endpoint_returns_jpeg(client_with_mock):
    """GET /api/images/{filename}/thumbnail returns image/jpeg content type."""
    client, mock_service = client_with_mock
    
    response = client.get("/api/images/test.jpg/thumbnail")
    
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"\xff\xd8\xff\xe0JFIF"


def test_thumbnail_endpoint_sets_cache_headers(client_with_mock):
    """Thumbnail response includes Cache-Control header."""
    client, mock_service = client_with_mock
    
    response = client.get("/api/images/test.jpg/thumbnail")
    
    assert response.status_code == 200
    assert "cache-control" in response.headers
    assert "public" in response.headers["cache-control"]
    assert "max-age=3600" in response.headers["cache-control"]


def test_thumbnail_endpoint_includes_correlation_id(client_with_mock):
    """Thumbnail response includes X-Correlation-ID header."""
    client, mock_service = client_with_mock
    
    response = client.get("/api/images/test.jpg/thumbnail")
    
    assert response.status_code == 200
    assert "x-correlation-id" in response.headers


def test_thumbnail_endpoint_accepts_size_parameter(client_with_mock):
    """Thumbnail endpoint accepts size query parameter."""
    client, mock_service = client_with_mock
    
    # Track the size parameter that was passed
    received_size = None
    original_get_thumbnail = mock_service.get_thumbnail
    
    async def capturing_get_thumbnail(filename: str, size: str = "w960h640") -> bytes:
        nonlocal received_size
        received_size = size
        return await original_get_thumbnail(filename, size)
    
    mock_service.get_thumbnail = capturing_get_thumbnail
    
    response = client.get("/api/images/test.jpg/thumbnail?size=w640h480")
    
    assert response.status_code == 200
    assert received_size == "w640h480"


def test_thumbnail_endpoint_rejects_invalid_size(client_with_mock):
    """Thumbnail endpoint rejects invalid size parameter."""
    client, mock_service = client_with_mock
    
    response = client.get("/api/images/test.jpg/thumbnail?size=invalid")
    
    assert response.status_code == 422  # Validation error


def test_thumbnail_endpoint_404_not_found(client_with_mock):
    """Thumbnail endpoint returns 404 for missing images."""
    client, mock_service = client_with_mock
    mock_service._error = StorageError("Failed to get thumbnail: path/not_found")
    
    response = client.get("/api/images/nonexistent.jpg/thumbnail")
    
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_thumbnail_endpoint_500_on_error(client_with_mock):
    """Thumbnail endpoint returns 500 on unexpected errors."""
    client, mock_service = client_with_mock
    mock_service._error = StorageError("Connection timeout")
    
    response = client.get("/api/images/test.jpg/thumbnail")
    
    assert response.status_code == 500
    assert "failed to generate thumbnail" in response.json()["detail"].lower()


def test_thumbnail_endpoint_requires_admin_when_auto_view_disabled():
    """Thumbnail requires admin when AUTO_VIEW is disabled."""
    mock_service = MockWebImageService(auto_view_enabled=False)
    
    app.dependency_overrides[get_service] = lambda: mock_service
    
    # Also mock admin check functions
    with patch("publisher_v2.web.app.is_admin_configured") as mock_admin_configured:
        mock_admin_configured.return_value = True
        with patch("publisher_v2.web.app.require_admin") as mock_require_admin:
            from fastapi import HTTPException
            mock_require_admin.side_effect = HTTPException(
                status_code=401,
                detail="Admin required"
            )
            
            with TestClient(app) as client:
                response = client.get("/api/images/test.jpg/thumbnail")
                
                assert response.status_code == 401
    
    app.dependency_overrides.clear()


def test_thumbnail_endpoint_503_when_admin_not_configured():
    """Thumbnail returns 503 when AUTO_VIEW disabled and admin not configured."""
    mock_service = MockWebImageService(auto_view_enabled=False)
    
    app.dependency_overrides[get_service] = lambda: mock_service
    
    with patch("publisher_v2.web.app.is_admin_configured") as mock_admin_configured:
        mock_admin_configured.return_value = False
        
        with TestClient(app) as client:
            response = client.get("/api/images/test.jpg/thumbnail")
            
            assert response.status_code == 503
            assert "admin mode" in response.json()["detail"].lower()
    
    app.dependency_overrides.clear()


def test_thumbnail_endpoint_url_encodes_filename(client_with_mock):
    """Thumbnail endpoint handles URL-encoded filenames correctly."""
    client, mock_service = client_with_mock
    
    # Track the filename that was passed
    received_filename = None
    original_get_thumbnail = mock_service.get_thumbnail
    
    async def capturing_get_thumbnail(filename: str, size: str = "w960h640") -> bytes:
        nonlocal received_filename
        received_filename = filename
        return await original_get_thumbnail(filename, size)
    
    mock_service.get_thumbnail = capturing_get_thumbnail
    
    # Filename with spaces and special characters
    response = client.get("/api/images/my%20photo%20%281%29.jpg/thumbnail")
    
    assert response.status_code == 200
    # The filename should be decoded by FastAPI
    assert received_filename == "my photo (1).jpg"


def test_image_response_model_has_thumbnail_url():
    """ImageResponse model includes thumbnail_url field."""
    from publisher_v2.web.models import ImageResponse
    
    response = ImageResponse(
        filename="test.jpg",
        temp_url="https://dropbox.com/full/test.jpg",
        thumbnail_url="/api/images/test.jpg/thumbnail",
        sha256=None,
        caption="Test caption",
        has_sidecar=False,
    )
    
    assert response.thumbnail_url == "/api/images/test.jpg/thumbnail"
    assert response.temp_url == "https://dropbox.com/full/test.jpg"


def test_image_response_model_thumbnail_url_optional():
    """ImageResponse model allows thumbnail_url to be None."""
    from publisher_v2.web.models import ImageResponse
    
    # Should not raise - thumbnail_url is optional
    response = ImageResponse(
        filename="test.jpg",
        temp_url="https://dropbox.com/full/test.jpg",
        sha256=None,
        caption="Test caption",
        has_sidecar=False,
    )
    
    assert response.thumbnail_url is None
