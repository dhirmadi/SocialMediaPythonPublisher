import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from publisher_v2.web.app import app
from publisher_v2.web.service import WebImageService
from publisher_v2.web.models import ImageResponse, ImageListResponse

@pytest.fixture
def mock_service():
    service = MagicMock(spec=WebImageService)
    service.config = MagicMock()
    service.config.features.auto_view_enabled = True  # Simplify auth for tests
    return service

@pytest.fixture
def client(mock_service):
    from fastapi.testclient import TestClient
    
    # Override the dependency
    app.dependency_overrides[WebImageService] = lambda: mock_service
    # Need to override get_service actually used in Depends
    from publisher_v2.web.app import get_service
    app.dependency_overrides[get_service] = lambda: mock_service
    
    with TestClient(app) as c:
        yield c
    
    app.dependency_overrides = {}

def test_list_images(client, mock_service):
    mock_service.list_images = AsyncMock(return_value={"filenames": ["a.jpg", "b.jpg"], "count": 2})
    
    resp = client.get("/api/images/list")
    assert resp.status_code == 200
    data = resp.json()
    assert data["filenames"] == ["a.jpg", "b.jpg"]
    assert data["count"] == 2

def test_get_specific_image(client, mock_service):
    img = ImageResponse(filename="a.jpg", temp_url="http://foo.com/a.jpg", has_sidecar=False)
    mock_service.get_image_details = AsyncMock(return_value=img)
    
    resp = client.get("/api/images/a.jpg")
    assert resp.status_code == 200
    assert resp.json()["filename"] == "a.jpg"
    mock_service.get_image_details.assert_called_with("a.jpg")

def test_get_specific_image_not_found(client, mock_service):
    mock_service.get_image_details = AsyncMock(side_effect=FileNotFoundError("Not found"))
    
    resp = client.get("/api/images/missing.jpg")
    assert resp.status_code == 404

def test_route_ordering(client, mock_service):
    # Ensure /list is not captured by /{filename}
    mock_service.list_images = AsyncMock(return_value={"filenames": [], "count": 0})
    
    resp = client.get("/api/images/list")
    assert resp.status_code == 200
    # If captured by /{filename}, it might call get_image_details("list") or fail
    mock_service.list_images.assert_called_once()

