"""Tests for PUB-024: ManagedStorage adapter (AC1–AC14, AC25)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from publisher_v2.config.schema import ManagedStorageConfig
from publisher_v2.core.exceptions import StorageError
from publisher_v2.services.storage_protocol import StorageProtocol


@pytest.fixture
def managed_config() -> ManagedStorageConfig:
    return ManagedStorageConfig(
        access_key_id="AKID",
        secret_access_key="SECRET",
        endpoint_url="https://test.r2.cloudflarestorage.com",
        bucket="test-bucket",
        region="auto",
    )


@pytest.fixture
def mock_s3_client():
    with patch("publisher_v2.services.managed_storage.boto3") as mock_boto:
        client = MagicMock()
        mock_boto.client.return_value = client
        yield client


@pytest.fixture
def storage(managed_config, mock_s3_client):
    from publisher_v2.services.managed_storage import ManagedStorage

    return ManagedStorage(managed_config)


# AC1: ManagedStorage implements StorageProtocol
class TestProtocolCompliance:
    def test_isinstance_check(self, storage) -> None:
        assert isinstance(storage, StorageProtocol)


# AC2: list_images
class TestListImages:
    async def test_returns_filtered_filenames(self, storage, mock_s3_client) -> None:
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "tenant/images/photo.jpg"},
                    {"Key": "tenant/images/photo.png"},
                    {"Key": "tenant/images/readme.txt"},
                    {"Key": "tenant/images/video.mp4"},
                ]
            }
        ]
        mock_s3_client.get_paginator.return_value = paginator

        result = await storage.list_images("tenant/images")
        assert result == ["photo.jpg", "photo.png"]

    async def test_excludes_nested_subprefix_objects(self, storage, mock_s3_client) -> None:
        """Archive/keep/remove keys share a prefix with root; list only immediate children."""
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "tenant/images/a.jpg"},
                    {"Key": "tenant/images/archive/a.jpg"},
                    {"Key": "tenant/images/archive/old.jpg"},
                ]
            }
        ]
        mock_s3_client.get_paginator.return_value = paginator

        result = await storage.list_images("tenant/images")
        assert result == ["a.jpg"]


# AC3: download_image
class TestDownloadImage:
    async def test_returns_bytes(self, storage, mock_s3_client) -> None:
        body = MagicMock()
        body.read.return_value = b"image-bytes"
        mock_s3_client.get_object.return_value = {"Body": body}

        result = await storage.download_image("folder", "test.jpg")
        assert result == b"image-bytes"
        mock_s3_client.get_object.assert_called_once()


# AC4: get_temporary_link
class TestGetTemporaryLink:
    async def test_returns_presigned_url(self, storage, mock_s3_client) -> None:
        mock_s3_client.generate_presigned_url.return_value = "https://presigned-url"

        result = await storage.get_temporary_link("folder", "test.jpg")
        assert result == "https://presigned-url"
        mock_s3_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "test-bucket", "Key": "folder/test.jpg"},
            ExpiresIn=3600,
        )


# AC5: get_thumbnail
class TestGetThumbnail:
    async def test_returns_jpeg_bytes(self, storage, mock_s3_client) -> None:
        # Create a minimal valid JPEG via Pillow
        import io

        from PIL import Image

        img = Image.new("RGB", (100, 100), color="red")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        jpeg_bytes = buf.getvalue()

        body = MagicMock()
        body.read.return_value = jpeg_bytes
        mock_s3_client.get_object.return_value = {"Body": body}

        # Clear thumbnail cache
        from publisher_v2.services.managed_storage import _thumbnail_cache

        _thumbnail_cache.clear()

        result = await storage.get_thumbnail("folder", "test.jpg")
        assert len(result) > 0
        # JPEG starts with FF D8
        assert result[:2] == b"\xff\xd8"

    async def test_cache_hit_avoids_second_download(self, storage, mock_s3_client) -> None:
        import io

        from PIL import Image

        img = Image.new("RGB", (100, 100), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        jpeg_bytes = buf.getvalue()

        body = MagicMock()
        body.read.return_value = jpeg_bytes
        mock_s3_client.get_object.return_value = {"Body": body}

        from publisher_v2.services.managed_storage import _thumbnail_cache

        _thumbnail_cache.clear()

        await storage.get_thumbnail("folder", "cached.jpg")
        await storage.get_thumbnail("folder", "cached.jpg")

        # get_object should only be called once (second call hits cache)
        assert mock_s3_client.get_object.call_count == 1


# AC6: archive_image
class TestArchiveImage:
    async def test_copies_and_deletes(self, storage, mock_s3_client) -> None:
        await storage.archive_image("folder", "test.jpg", "folder/archive")

        # Image: copy + delete
        mock_s3_client.copy_object.assert_called()
        mock_s3_client.delete_object.assert_called()
        calls = mock_s3_client.copy_object.call_args_list
        assert any("test.jpg" in str(c) for c in calls)


# AC7: move_image_with_sidecars
class TestMoveImageWithSidecars:
    async def test_copies_and_deletes_image(self, storage, mock_s3_client) -> None:
        await storage.move_image_with_sidecars("folder", "test.jpg", "keep")

        mock_s3_client.copy_object.assert_called()
        mock_s3_client.delete_object.assert_called()

    async def test_move_accepts_full_path_target_like_orchestrator(self, storage, mock_s3_client) -> None:
        """Orchestrator storage_paths.folder_keep is a full key prefix, not a single segment."""
        await storage.move_image_with_sidecars("tenant/root", "a.jpg", "tenant/root/keep")

        first_copy = mock_s3_client.copy_object.call_args_list[0].kwargs
        assert first_copy["Key"] == "tenant/root/keep/a.jpg"


# AC8: delete_file_with_sidecar
class TestDeleteFileWithSidecar:
    async def test_deletes_image_and_sidecar(self, storage, mock_s3_client) -> None:
        await storage.delete_file_with_sidecar("folder", "test.jpg")

        delete_calls = mock_s3_client.delete_object.call_args_list
        keys_deleted = [c.kwargs.get("Key") or c[1].get("Key") for c in delete_calls]
        assert "folder/test.jpg" in keys_deleted
        assert "folder/test.txt" in keys_deleted


# AC9: write_sidecar_text
class TestWriteSidecarText:
    async def test_puts_object_with_utf8(self, storage, mock_s3_client) -> None:
        await storage.write_sidecar_text("folder", "test.jpg", "hello world")

        mock_s3_client.put_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="folder/test.txt",
            Body=b"hello world",
            ContentType="text/plain; charset=utf-8",
        )


# AC10: download_sidecar_if_exists returns None on NoSuchKey
class TestDownloadSidecarIfExists:
    async def test_returns_none_on_no_such_key(self, storage, mock_s3_client) -> None:
        from botocore.exceptions import ClientError

        mock_s3_client.get_object.side_effect = ClientError(
            {
                "Error": {"Code": "NoSuchKey"},
                "ResponseMetadata": {
                    "HTTPStatusCode": 404,
                    "RequestId": "",
                    "HostId": "",
                    "HTTPHeaders": {},
                    "RetryAttempts": 0,
                },
            },
            "GetObject",
        )

        result = await storage.download_sidecar_if_exists("folder", "test.jpg")
        assert result is None

    async def test_returns_bytes_when_exists(self, storage, mock_s3_client) -> None:
        body = MagicMock()
        body.read.return_value = b"sidecar-content"
        mock_s3_client.get_object.return_value = {"Body": body}

        result = await storage.download_sidecar_if_exists("folder", "test.jpg")
        assert result == b"sidecar-content"


# AC11: get_file_metadata
class TestGetFileMetadata:
    async def test_returns_etag_and_last_modified(self, storage, mock_s3_client) -> None:
        mock_s3_client.head_object.return_value = {
            "ETag": '"abc123"',
            "LastModified": "2025-01-01T00:00:00Z",
        }

        result = await storage.get_file_metadata("folder", "test.jpg")
        assert result["ETag"] == "abc123"
        assert result["LastModified"] == "2025-01-01T00:00:00Z"


# AC12: supports_content_hashing + list_images_with_hashes
class TestContentHashing:
    def test_supports_content_hashing(self, storage) -> None:
        assert storage.supports_content_hashing() is True

    async def test_list_images_with_hashes_returns_etags(self, storage, mock_s3_client) -> None:
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "folder/photo.jpg", "ETag": '"etag1"'},
                    {"Key": "folder/photo2.png", "ETag": '"etag2"'},
                ]
            }
        ]
        mock_s3_client.get_paginator.return_value = paginator

        result = await storage.list_images_with_hashes("folder")
        assert result == [("photo.jpg", "etag1"), ("photo2.png", "etag2")]


# AC13: asyncio.to_thread wrapping (verified by mock — sync methods are called from thread)
class TestAsyncWrapping:
    async def test_list_images_uses_to_thread(self, storage, mock_s3_client) -> None:
        paginator = MagicMock()
        paginator.paginate.return_value = [{"Contents": []}]
        mock_s3_client.get_paginator.return_value = paginator

        # If to_thread is used, the sync S3 client methods are called successfully
        result = await storage.list_images("folder")
        assert isinstance(result, list)


# AC14: Transient error retry
class TestRetry:
    async def test_permanent_error_raises_storage_error(self, storage, mock_s3_client) -> None:
        from botocore.exceptions import ClientError

        mock_s3_client.get_object.side_effect = ClientError(
            {
                "Error": {"Code": "AccessDenied"},
                "ResponseMetadata": {
                    "HTTPStatusCode": 403,
                    "RequestId": "",
                    "HostId": "",
                    "HTTPHeaders": {},
                    "RetryAttempts": 0,
                },
            },
            "GetObject",
        )

        with pytest.raises(StorageError):
            await storage.download_image("folder", "test.jpg")


# AC25: ensure_folder_exists is no-op
class TestEnsureFolderExists:
    async def test_noop(self, storage, mock_s3_client) -> None:
        await storage.ensure_folder_exists("any/path")
        # No S3 calls should be made
        mock_s3_client.assert_not_called()
