import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from caption_pipeline_fakes import make_app_config

from publisher_v2.config.runtime_settings import RuntimeSettings
from publisher_v2.config.schema import (
    ContentConfig,
    FeaturesConfig,
)
from publisher_v2.web.service import WebImageService


@pytest.fixture
def mock_storage():
    storage = MagicMock()
    storage.ensure_folder_exists = AsyncMock()
    return storage


@pytest.fixture
def service(mock_storage):
    # Construct a valid minimal config to satisfy Pydantic
    config = make_app_config(
        dropbox={"refresh_token": "t", "image_folder": "/photos", "folder_keep": "keep", "folder_remove": "remove"},
        storage_paths={"image_folder": "/photos", "folder_keep": "keep", "folder_remove": "remove"},
        openai={"api_key": "sk-testkey"},  # pragma: allowlist secret
        content=ContentConfig(),
        features=FeaturesConfig(keep_enabled=True, remove_enabled=True),
    )

    # Create service without calling __init__ to avoid config loading
    svc = object.__new__(WebImageService)
    # #143: __init__ is skipped here, so inject the settings the service would have read.
    svc._settings = RuntimeSettings()
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
    service.config.storage_paths.folder_keep = None
    service.config.storage_paths.folder_remove = None

    await service.verify_curation_folders()

    mock_storage.ensure_folder_exists.assert_not_called()


@pytest.mark.asyncio
async def test_verify_curation_folders_handles_slashes(service, mock_storage):
    # Ensure it constructs path correctly if image_folder has trailing slash
    service.config.dropbox.image_folder = "/photos/"

    await service.verify_curation_folders()

    mock_storage.ensure_folder_exists.assert_any_call("/photos/keep")
