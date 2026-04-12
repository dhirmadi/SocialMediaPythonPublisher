"""Tests for PUB-031 Phase D: library_enabled feature flag (AC19, AC20)."""

from __future__ import annotations

import pytest

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    FeaturesConfig,
    ManagedStorageConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
)


class TestLibraryEnabledFeatureFlag:
    """AC19: FeaturesConfig.library_enabled defaults to False."""

    def test_library_enabled_defaults_to_false(self) -> None:
        features = FeaturesConfig()
        assert features.library_enabled is False

    def test_library_enabled_can_be_set_true(self) -> None:
        features = FeaturesConfig(library_enabled=True)
        assert features.library_enabled is True

    def test_library_enabled_auto_set_for_managed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When config.managed is not None, library_enabled should be auto-set to True at startup."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

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

        # Import the helper that resolves the flag
        from publisher_v2.config.features import resolve_library_enabled

        result = resolve_library_enabled(cfg)
        assert result is True

    def test_library_disabled_by_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """FEATURE_LIBRARY=false overrides auto-enable for managed instances."""
        monkeypatch.setenv("FEATURE_LIBRARY", "false")

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

        from publisher_v2.config.features import resolve_library_enabled

        result = resolve_library_enabled(cfg)
        assert result is False

    def test_library_disabled_for_dropbox(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When config.managed is None (Dropbox-only), library_enabled stays False."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        from publisher_v2.config.schema import DropboxConfig

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

        from publisher_v2.config.features import resolve_library_enabled

        result = resolve_library_enabled(cfg)
        assert result is False
