"""Tests for PUB-024: Storage factory (AC17)."""

from __future__ import annotations

from unittest.mock import patch

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    ManagedStorageConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
)
from publisher_v2.services.storage_factory import create_storage


def test_factory_returns_dropbox_storage() -> None:
    cfg = ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k",
            app_secret="s",
            refresh_token="r",
            image_folder="/Photos",
        ),
        storage_paths=StoragePathConfig(image_folder="/Photos"),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(),
        content=ContentConfig(),
    )
    with patch("publisher_v2.services.storage.dropbox.Dropbox"):
        storage = create_storage(cfg)
        from publisher_v2.services.storage import DropboxStorage

        assert isinstance(storage, DropboxStorage)


def test_factory_returns_managed_storage() -> None:
    cfg = ApplicationConfig(
        managed=ManagedStorageConfig(
            access_key_id="AKID",
            secret_access_key="SECRET",
            endpoint_url="https://r2.example.com",
            bucket="bucket",
        ),
        storage_paths=StoragePathConfig(image_folder="tenant/instance"),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(),
        content=ContentConfig(),
    )
    with patch("publisher_v2.services.managed_storage.boto3"):
        storage = create_storage(cfg)
        from publisher_v2.services.managed_storage import ManagedStorage

        assert isinstance(storage, ManagedStorage)
