"""Tests for PUB-031 Phase D: library_enabled feature flag (AC19, AC20)."""

from __future__ import annotations

import pytest
from caption_pipeline_fakes import make_app_config

from publisher_v2.config.schema import (
    FeaturesConfig,
    ManagedStorageConfig,
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

        cfg = make_app_config(
            managed=ManagedStorageConfig(
                access_key_id="AKID",
                secret_access_key="SECRET",
                endpoint_url="https://r2.example.com",
                bucket="bucket",
            ),
            storage_paths={"image_folder": "tenant/instance"},
            content={"archive": True},
        )

        # #97 stage 1: helper lives in config/loader.py and takes managed presence
        from publisher_v2.config.loader import resolve_library_enabled_env

        result = resolve_library_enabled_env(cfg.managed is not None)
        assert result is True

    def test_library_disabled_by_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """FEATURE_LIBRARY=false overrides auto-enable for managed instances."""
        monkeypatch.setenv("FEATURE_LIBRARY", "false")

        cfg = make_app_config(
            managed=ManagedStorageConfig(
                access_key_id="AKID",
                secret_access_key="SECRET",
                endpoint_url="https://r2.example.com",
                bucket="bucket",
            ),
            storage_paths={"image_folder": "tenant/instance"},
            content={"archive": True},
        )

        from publisher_v2.config.loader import resolve_library_enabled_env

        result = resolve_library_enabled_env(cfg.managed is not None)
        assert result is False

    def test_library_disabled_for_dropbox(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When config.managed is None (Dropbox-only), library_enabled stays False."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        cfg = make_app_config(content={"archive": True})

        from publisher_v2.config.loader import resolve_library_enabled_env

        result = resolve_library_enabled_env(cfg.managed is not None)
        assert result is False
