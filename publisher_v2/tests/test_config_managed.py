"""Tests for PUB-024: Config/credential/standalone tests for managed provider (AC15-AC24)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    ManagedStorageConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
)


# AC15: ApplicationConfig model validator
class TestApplicationConfigValidator:
    def test_managed_only_validates(self) -> None:
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
        assert cfg.managed is not None
        assert cfg.dropbox is None

    def test_dropbox_only_validates(self) -> None:
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
        assert cfg.dropbox is not None
        assert cfg.managed is None

    def test_both_set_fails(self) -> None:
        with pytest.raises(ValidationError, match="Only one storage provider"):
            ApplicationConfig(
                dropbox=DropboxConfig(
                    app_key="k",
                    app_secret="s",
                    refresh_token="r",
                    image_folder="/Photos",
                ),
                managed=ManagedStorageConfig(
                    access_key_id="AKID",
                    secret_access_key="SECRET",
                    endpoint_url="https://r2.example.com",
                    bucket="bucket",
                ),
                storage_paths=StoragePathConfig(image_folder="/Photos"),
                openai=OpenAIConfig(api_key="sk-test"),
                platforms=PlatformsConfig(),
                content=ContentConfig(),
            )

    def test_neither_set_fails(self) -> None:
        with pytest.raises(ValidationError, match="Exactly one storage provider"):
            ApplicationConfig(
                storage_paths=StoragePathConfig(image_folder="/Photos"),
                openai=OpenAIConfig(api_key="sk-test"),
                platforms=PlatformsConfig(),
                content=ContentConfig(),
            )


# AC16: StoragePathConfig exists with correct fields
class TestStoragePathConfig:
    def test_fields_exist(self) -> None:
        sp = StoragePathConfig(image_folder="/Photos")
        assert sp.image_folder == "/Photos"
        assert sp.archive_folder == "archive"
        assert sp.folder_keep == "keep"
        assert sp.folder_remove == "reject"

    def test_custom_values(self) -> None:
        sp = StoragePathConfig(
            image_folder="tenant/instance",
            archive_folder="tenant/instance/archive",
            folder_keep="tenant/instance/keep",
            folder_remove="tenant/instance/remove",
        )
        assert sp.image_folder == "tenant/instance"
        assert sp.archive_folder == "tenant/instance/archive"


# AC19: OrchestratorConfigSource.__init__ no longer crashes without DROPBOX keys
class TestOrchestratorNoDropboxGuard:
    def test_init_succeeds_without_dropbox_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orch.example.com")
        monkeypatch.setenv("ORCHESTRATOR_SERVICE_TOKEN", "svc-token")
        monkeypatch.delenv("DROPBOX_APP_KEY", raising=False)
        monkeypatch.delenv("DROPBOX_APP_SECRET", raising=False)

        from publisher_v2.config.source import OrchestratorConfigSource

        # Should NOT raise ConfigurationError
        source = OrchestratorConfigSource()
        assert source.is_orchestrated()


# AC22: Standalone STORAGE_PROVIDER=managed
class TestStandaloneManagedProvider:
    def test_managed_env_builds_config(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        ini = tmp_path / "test.ini"
        ini.write_text(
            """
[openAI]
vision_model = gpt-4o

[Content]
archive = true
debug = false
"""
        )
        monkeypatch.setenv("STORAGE_PROVIDER", "managed")
        monkeypatch.setenv("STORAGE_PATHS", '{"root": "/managed/images", "archive": "/managed/archive"}')
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "AKID")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "SECRET")
        monkeypatch.setenv("R2_ENDPOINT_URL", "https://r2.example.com")
        monkeypatch.setenv("R2_BUCKET_NAME", "bucket")
        monkeypatch.setenv("R2_REGION", "auto")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-for-testing")

        from publisher_v2.config.loader import load_application_config

        cfg = load_application_config(str(ini))
        assert cfg.managed is not None
        assert cfg.managed.access_key_id == "AKID"
        assert cfg.managed.bucket == "bucket"
        assert cfg.dropbox is None
        assert cfg.storage_paths.image_folder == "/managed/images"


# AC23: Default Dropbox behavior preserved
class TestStandaloneDropboxPreserved:
    def test_default_dropbox_builds_config(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        ini = tmp_path / "test.ini"
        ini.write_text(
            """
[Dropbox]
image_folder = /Photos
archive = archive

[openAI]
vision_model = gpt-4o

[Content]
archive = true
debug = false
"""
        )
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_token")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-for-testing")
        monkeypatch.delenv("STORAGE_PROVIDER", raising=False)

        from publisher_v2.config.loader import load_application_config

        cfg = load_application_config(str(ini))
        assert cfg.dropbox is not None
        assert cfg.managed is None
        assert cfg.storage_paths.image_folder == "/Photos"


# AC24: ManagedStorageCredentials model
class TestManagedStorageCredentials:
    def test_credential_model_parses(self) -> None:
        from publisher_v2.config.credentials import ManagedStorageCredentials

        creds = ManagedStorageCredentials(
            provider="managed",
            version="abc123",
            access_key_id="AKID",
            secret_access_key="SECRET",
            endpoint_url="https://r2.example.com",
            bucket="publisher-media",
            region="auto",
        )
        assert creds.provider == "managed"
        assert creds.access_key_id == "AKID"
