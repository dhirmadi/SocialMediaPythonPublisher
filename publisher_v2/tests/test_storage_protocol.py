"""Tests for PUB-023: StorageProtocol extraction.

Covers AC1 (protocol exists with 14 methods), AC3 (DropboxStorage satisfies protocol),
AC4 (ThumbnailSize/ThumbnailFormat are StrEnum), AC5 (supports_content_hashing),
AC6 (BaseDummyStorage satisfies protocol).
"""

from __future__ import annotations

import inspect
from enum import StrEnum
from unittest.mock import patch

import pytest
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


# ---------------------------------------------------------------------------
# #96: FileMetadata, StorageNotSupportedError, ObjectStorageProtocol contract
# ---------------------------------------------------------------------------


class TestFileMetadataDataclass:
    def test_is_frozen_with_expected_fields(self) -> None:
        import dataclasses

        from publisher_v2.services.storage_protocol import FileMetadata

        meta = FileMetadata(file_id="id:1", revision="r1", modified_at="2026-01-01", size=10)
        assert (meta.file_id, meta.revision, meta.modified_at, meta.size) == ("id:1", "r1", "2026-01-01", 10)
        with pytest.raises(dataclasses.FrozenInstanceError):
            meta.file_id = "other"  # type: ignore[misc]


class TestStorageNotSupportedError:
    def test_is_not_implemented_error(self) -> None:
        from publisher_v2.services.storage_protocol import StorageNotSupportedError

        assert issubclass(StorageNotSupportedError, NotImplementedError)


class TestDropboxObjectOpsNotSupported:
    """Dropbox backend declines object-level ops loudly, not with AttributeError."""

    @pytest.fixture
    def dropbox_storage(self):
        from unittest.mock import MagicMock, patch

        from publisher_v2.config.schema import DropboxConfig
        from publisher_v2.services.storage import DropboxStorage

        cfg = DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        )
        with patch("publisher_v2.services.storage.dropbox.Dropbox", return_value=MagicMock()):
            return DropboxStorage(cfg)

    async def test_all_object_ops_raise_storage_not_supported(self, dropbox_storage) -> None:
        from publisher_v2.services.storage_protocol import StorageNotSupportedError

        with pytest.raises(StorageNotSupportedError):
            await dropbox_storage.list_objects("p/")
        with pytest.raises(StorageNotSupportedError):
            await dropbox_storage.put_object("k", b"d", "image/jpeg")
        with pytest.raises(StorageNotSupportedError):
            await dropbox_storage.head_object("k")
        with pytest.raises(StorageNotSupportedError):
            await dropbox_storage.delete_object("k")
        with pytest.raises(StorageNotSupportedError):
            await dropbox_storage.move_object("a", "b")

    async def test_get_file_metadata_returns_file_metadata(self, dropbox_storage) -> None:
        from unittest.mock import MagicMock

        import dropbox as dropbox_sdk

        from publisher_v2.services.storage_protocol import FileMetadata

        md = MagicMock(spec=dropbox_sdk.files.FileMetadata)
        md.id = "id:abc"
        md.rev = "rev-9"
        md.server_modified = None
        md.size = 123
        dropbox_storage.client.files_get_metadata.return_value = md
        meta = await dropbox_storage.get_file_metadata("/Photos", "a.jpg")
        assert isinstance(meta, FileMetadata)
        assert meta.file_id == "id:abc"
        assert meta.revision == "rev-9"


class TestManagedObjectOps:
    """ManagedStorage implements ObjectStorageProtocol against the S3 client."""

    @pytest.fixture
    def managed(self):
        from unittest.mock import MagicMock, patch

        from publisher_v2.config.schema import ManagedStorageConfig
        from publisher_v2.services.managed_storage import ManagedStorage

        cfg = ManagedStorageConfig(
            access_key_id="AKID",
            secret_access_key="SECRET",
            endpoint_url="https://test.r2.cloudflarestorage.com",
            bucket="bkt",
            region="auto",
        )
        with patch("publisher_v2.services.managed_storage.boto3") as boto:
            client = MagicMock()
            boto.client.return_value = client
            storage = ManagedStorage(cfg)
        return storage, client

    def test_is_instance_of_object_storage_protocol(self, managed) -> None:
        from publisher_v2.services.storage_protocol import ObjectStorageProtocol

        storage, _ = managed
        assert isinstance(storage, ObjectStorageProtocol)

    async def test_list_objects_page_shape_and_delimiter(self, managed) -> None:
        storage, client = managed
        client.list_objects_v2.return_value = {
            "Contents": [{"Key": "t/root/a.jpg", "Size": 10, "LastModified": "2026-01-01"}],
            "IsTruncated": True,
            "NextContinuationToken": "tok",
        }
        page = await storage.list_objects("t/root/", limit=50)
        assert page == {
            "items": [{"key": "t/root/a.jpg", "size": 10, "last_modified": "2026-01-01"}],
            "cursor": "tok",
            "is_truncated": True,
        }
        client.list_objects_v2.assert_called_once_with(Bucket="bkt", Prefix="t/root/", Delimiter="/", MaxKeys=50)

    async def test_list_objects_passes_cursor(self, managed) -> None:
        storage, client = managed
        client.list_objects_v2.return_value = {"Contents": [], "IsTruncated": False}
        await storage.list_objects("p/", cursor="next-token", limit=10)
        assert client.list_objects_v2.call_args.kwargs["ContinuationToken"] == "next-token"

    async def test_put_head_delete_move_and_metering(self, managed) -> None:
        storage, client = managed
        client.head_object.return_value = {"ContentLength": 5, "ETag": '"e1"', "LastModified": "t"}

        await storage.put_object("k", b"data", "image/jpeg")
        client.put_object.assert_called_once_with(Bucket="bkt", Key="k", Body=b"data", ContentType="image/jpeg")

        head = await storage.head_object("k")
        assert head == {"size": 5, "etag": "e1", "last_modified": "t"}

        await storage.delete_object("k")
        client.delete_object.assert_called_once_with(Bucket="bkt", Key="k")

        await storage.move_object("a", "b")
        client.copy_object.assert_called_once_with(Bucket="bkt", Key="b", CopySource={"Bucket": "bkt", "Key": "a"})

        # PUB-045 metering: put=1, head=1, delete=1, move=2 -> 5 ops
        assert storage.drain_ops_count() == 5

    async def test_head_object_returns_none_on_missing(self, managed) -> None:
        from botocore.exceptions import ClientError

        storage, client = managed
        client.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")
        assert await storage.head_object("missing") is None
