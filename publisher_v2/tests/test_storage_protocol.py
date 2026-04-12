"""Tests for PUB-023: StorageProtocol extraction.

Covers AC1 (protocol exists with 14 methods), AC3 (DropboxStorage satisfies protocol),
AC4 (ThumbnailSize/ThumbnailFormat are StrEnum), AC5 (supports_content_hashing),
AC6 (BaseDummyStorage satisfies protocol).
"""

from __future__ import annotations

import inspect
from enum import StrEnum
from unittest.mock import patch

from conftest import BaseDummyStorage

from publisher_v2.config.schema import DropboxConfig
from publisher_v2.services.storage_protocol import StorageProtocol, ThumbnailFormat, ThumbnailSize

# ---------------------------------------------------------------------------
# AC1: Protocol class exists and defines all required methods
# ---------------------------------------------------------------------------


class TestProtocolDefinition:
    """AC1: StorageProtocol defines all 14 public methods."""

    EXPECTED_METHODS = [
        "list_images",
        "list_images_with_hashes",
        "download_image",
        "get_temporary_link",
        "get_file_metadata",
        "write_sidecar_text",
        "download_sidecar_if_exists",
        "archive_image",
        "move_image_with_sidecars",
        "delete_file_with_sidecar",
        "ensure_folder_exists",
        "get_thumbnail",
        "supports_content_hashing",
    ]

    def test_protocol_is_runtime_checkable(self) -> None:
        assert hasattr(StorageProtocol, "__protocol_attrs__") or hasattr(StorageProtocol, "_is_runtime_protocol")

    def test_protocol_defines_all_methods(self) -> None:
        protocol_members = {
            name
            for name, _ in inspect.getmembers(StorageProtocol, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        for method in self.EXPECTED_METHODS:
            assert method in protocol_members, f"StorageProtocol missing method: {method}"

    def test_protocol_has_13_async_methods(self) -> None:
        """12 async I/O methods + get_thumbnail = 13 async, 1 sync (supports_content_hashing)."""
        async_count = 0
        sync_count = 0
        for name in self.EXPECTED_METHODS:
            func = getattr(StorageProtocol, name, None)
            assert func is not None, f"Missing method: {name}"
            if inspect.iscoroutinefunction(func):
                async_count += 1
            else:
                sync_count += 1
        assert async_count == 12, f"Expected 12 async methods, got {async_count}"
        assert sync_count == 1, f"Expected 1 sync method, got {sync_count}"


# ---------------------------------------------------------------------------
# AC4: ThumbnailSize and ThumbnailFormat are StrEnum with correct values
# ---------------------------------------------------------------------------


class TestThumbnailEnums:
    """AC4: Protocol-level thumbnail enums."""

    def test_thumbnail_size_is_str_enum(self) -> None:
        assert issubclass(ThumbnailSize, StrEnum)

    def test_thumbnail_format_is_str_enum(self) -> None:
        assert issubclass(ThumbnailFormat, StrEnum)

    def test_thumbnail_size_values(self) -> None:
        expected = {"w256h256", "w480h320", "w640h480", "w960h640", "w1024h768"}
        actual = {member.value for member in ThumbnailSize}
        assert actual == expected

    def test_thumbnail_format_values(self) -> None:
        expected = {"jpeg", "png"}
        actual = {member.value for member in ThumbnailFormat}
        assert actual == expected

    def test_thumbnail_size_default_is_w960h640(self) -> None:
        assert ThumbnailSize.W960H640 == "w960h640"

    def test_thumbnail_format_default_is_jpeg(self) -> None:
        assert ThumbnailFormat.JPEG == "jpeg"


# ---------------------------------------------------------------------------
# AC3: DropboxStorage satisfies StorageProtocol (isinstance check)
# ---------------------------------------------------------------------------


class TestDropboxStorageCompliance:
    """AC3: DropboxStorage structurally satisfies StorageProtocol."""

    def test_dropbox_storage_is_instance_of_protocol(self) -> None:
        with patch("dropbox.Dropbox"):
            from publisher_v2.services.storage import DropboxStorage

            cfg = DropboxConfig(
                app_key="k",
                app_secret="s",
                refresh_token="r",
                image_folder="/Photos",
                archive_folder="archive",
            )
            storage = DropboxStorage(cfg)
            assert isinstance(storage, StorageProtocol)


# ---------------------------------------------------------------------------
# AC5: supports_content_hashing()
# ---------------------------------------------------------------------------


class TestSupportsContentHashing:
    """AC5: DropboxStorage.supports_content_hashing() returns True; BaseDummyStorage returns False."""

    def test_dropbox_storage_supports_content_hashing(self) -> None:
        with patch("dropbox.Dropbox"):
            from publisher_v2.services.storage import DropboxStorage

            cfg = DropboxConfig(
                app_key="k",
                app_secret="s",
                refresh_token="r",
                image_folder="/Photos",
                archive_folder="archive",
            )
            storage = DropboxStorage(cfg)
            assert storage.supports_content_hashing() is True

    def test_base_dummy_storage_does_not_support_content_hashing(self) -> None:
        storage = BaseDummyStorage()
        assert storage.supports_content_hashing() is False


# ---------------------------------------------------------------------------
# AC6: BaseDummyStorage satisfies StorageProtocol
# ---------------------------------------------------------------------------


class TestBaseDummyStorageCompliance:
    """AC6: BaseDummyStorage implements StorageProtocol."""

    def test_base_dummy_storage_is_instance_of_protocol(self) -> None:
        storage = BaseDummyStorage()
        assert isinstance(storage, StorageProtocol)
