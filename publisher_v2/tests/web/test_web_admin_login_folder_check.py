import logging
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from publisher_v2.web.service import WebImageService
from publisher_v2.config.schema import (
    ApplicationConfig, 
    DropboxConfig, 
    FeaturesConfig,
    OpenAIConfig,
    PlatformsConfig,
    ContentConfig,
    CaptionFileConfig,
    WebConfig
)

@pytest.fixture
def mock_storage():
    storage = MagicMock()
    storage.ensure_folder_exists = AsyncMock()
    return storage

@pytest.fixture
def service(mock_storage):
    # Construct a valid minimal config to satisfy Pydantic
    dropbox_config = DropboxConfig(
        app_key="k", 
        app_secret="s", 
        refresh_token="t",
        image_folder="/photos",
        folder_keep="keep",
        folder_remove="remove"
    )
    openai_config = OpenAIConfig(api_key="sk-testkey")
    platforms_config = PlatformsConfig()
    content_config = ContentConfig()
    features_config = FeaturesConfig(keep_enabled=True, remove_enabled=True)
    
    config = ApplicationConfig(
        dropbox=dropbox_config,
        openai=openai_config,
        platforms=platforms_config,
        content=content_config,
        features=features_config
    )
    
    # Create service without calling __init__ to avoid config loading
    svc = object.__new__(WebImageService)
    svc.config = config
    svc.storage = mock_storage
    # Suppress normal logging
    svc.logger = logging.getLogger("test_logger")
    return svc

@pytest.mark.asyncio
async def test_verify_curation_folders_checks_both_when_enabled(service, mock_storage):
    await service.verify_curation_folders()
    
    assert mock_storage.ensure_folder_exists.call_count == 2
    mock_storage.ensure_folder_exists.assert_any_call("/photos/keep")
    mock_storage.ensure_folder_exists.assert_any_call("/photos/remove")

@pytest.mark.asyncio
async def test_verify_curation_folders_skips_disabled_features(service, mock_storage):
    service.config.features.keep_enabled = False
    service.config.features.remove_enabled = False
    
    await service.verify_curation_folders()
    
    mock_storage.ensure_folder_exists.assert_not_called()

@pytest.mark.asyncio
async def test_verify_curation_folders_skips_unconfigured_folders(service, mock_storage):
    service.config.dropbox.folder_keep = None
    service.config.dropbox.folder_remove = None
    
    await service.verify_curation_folders()
    
    mock_storage.ensure_folder_exists.assert_not_called()

@pytest.mark.asyncio
async def test_verify_curation_folders_handles_slashes(service, mock_storage):
    # Ensure it constructs path correctly if image_folder has trailing slash
    service.config.dropbox.image_folder = "/photos/"
    
    await service.verify_curation_folders()
    
    mock_storage.ensure_folder_exists.assert_any_call("/photos/keep")
