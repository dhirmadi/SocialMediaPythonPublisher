"""
Tests for storage.py error handling paths (QC-002).

These tests cover the uncovered error handling lines in DropboxStorage:
- Lines 49-50: write_sidecar_text exception handling
- Lines 68: _is_sidecar_not_found_error edge case
- Lines 123-124: get_file_metadata exception handling
- Lines 145-146: list_images exception handling
- Lines 174-175: list_images_with_hashes exception handling
- Lines 190-191: download_image exception handling
- Lines 206-207: get_temporary_link exception handling
- Lines 219-233: ensure_folder_exists logic
- Lines 270-271: move_image_with_sidecars exception handling
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from dropbox.exceptions import ApiError

from publisher_v2.config.schema import DropboxConfig
from publisher_v2.core.exceptions import StorageError
from publisher_v2.services.storage import DropboxStorage


@pytest.fixture
def storage_config() -> DropboxConfig:
    """Standard config for storage tests."""
    return DropboxConfig(
        app_key="test_key",
        app_secret="test_secret",
        refresh_token="test_refresh",
        image_folder="/ImagesToday",
        archive_folder="archive",
    )


@pytest.fixture
def storage_with_mock_client(storage_config: DropboxConfig, monkeypatch: pytest.MonkeyPatch) -> DropboxStorage:
    """Storage instance with mocked Dropbox client."""
    storage = DropboxStorage(storage_config)
    mock_client = MagicMock()
    monkeypatch.setattr(storage, "client", mock_client)
    return storage


def _create_api_error(error_type: str = "generic") -> ApiError:
    """Create a mock ApiError for testing."""
    class MockError:
        def is_path(self) -> bool:
            return error_type == "path"
        
        def get_path(self) -> SimpleNamespace:
            if error_type == "not_found":
                return SimpleNamespace(is_not_found=lambda: True)
            elif error_type == "conflict":
                return SimpleNamespace(is_conflict=lambda: True, is_not_found=lambda: False)
            return SimpleNamespace(is_not_found=lambda: False, is_conflict=lambda: False)
    
    return ApiError("request_id", MockError(), "error", "en-US")


class TestWriteSidecarTextErrorHandling:
    """Tests for write_sidecar_text exception handling (lines 49-50)."""
    
    @pytest.mark.asyncio
    async def test_write_sidecar_raises_storage_error_on_api_error(
        self, storage_with_mock_client: DropboxStorage
    ) -> None:
        """Verify write_sidecar_text wraps ApiError in StorageError."""
        storage_with_mock_client.client.files_upload.side_effect = _create_api_error()
        
        with pytest.raises(StorageError, match="Failed to upload sidecar"):
            await storage_with_mock_client.write_sidecar_text("/Photos", "image.jpg", "caption")


class TestIsSidecarNotFoundError:
    """Tests for _is_sidecar_not_found_error edge cases (line 68)."""
    
    def test_returns_false_when_error_attr_is_none(self) -> None:
        """Verify returns False when error attribute is None."""
        exc = ApiError("req", None, "msg", "en")  # type: ignore[arg-type]
        assert DropboxStorage._is_sidecar_not_found_error(exc) is False
    
    def test_returns_false_when_not_path_error(self) -> None:
        """Verify returns False when error is not a path error."""
        class MockError:
            def is_path(self) -> bool:
                return False
        
        exc = ApiError("req", MockError(), "msg", "en")
        assert DropboxStorage._is_sidecar_not_found_error(exc) is False
    
    def test_returns_false_when_path_error_but_not_not_found(self) -> None:
        """Verify returns False when path error is not 'not_found'."""
        class MockPathError:
            def is_not_found(self) -> bool:
                return False
        
        class MockError:
            def is_path(self) -> bool:
                return True
            def get_path(self) -> MockPathError:
                return MockPathError()
        
        exc = ApiError("req", MockError(), "msg", "en")
        assert DropboxStorage._is_sidecar_not_found_error(exc) is False
    
    def test_returns_true_when_path_not_found(self) -> None:
        """Verify returns True when path error is 'not_found'."""
        class MockPathError:
            def is_not_found(self) -> bool:
                return True
        
        class MockError:
            def is_path(self) -> bool:
                return True
            def get_path(self) -> MockPathError:
                return MockPathError()
        
        exc = ApiError("req", MockError(), "msg", "en")
        assert DropboxStorage._is_sidecar_not_found_error(exc) is True


class TestGetFileMetadataErrorHandling:
    """Tests for get_file_metadata exception handling (lines 123-124)."""
    
    @pytest.mark.asyncio
    async def test_get_file_metadata_raises_storage_error(
        self, storage_with_mock_client: DropboxStorage
    ) -> None:
        """Verify get_file_metadata wraps ApiError in StorageError."""
        storage_with_mock_client.client.files_get_metadata.side_effect = _create_api_error()
        
        with pytest.raises(StorageError, match="Failed to get metadata"):
            await storage_with_mock_client.get_file_metadata("/Photos", "image.jpg")


class TestListImagesErrorHandling:
    """Tests for list_images exception handling (lines 145-146)."""
    
    @pytest.mark.asyncio
    async def test_list_images_raises_storage_error(
        self, storage_with_mock_client: DropboxStorage
    ) -> None:
        """Verify list_images wraps ApiError in StorageError."""
        storage_with_mock_client.client.files_list_folder.side_effect = _create_api_error()
        
        with pytest.raises(StorageError, match="Failed to list images"):
            await storage_with_mock_client.list_images("/Photos")


class TestListImagesWithHashesErrorHandling:
    """Tests for list_images_with_hashes exception handling (lines 174-175)."""
    
    @pytest.mark.asyncio
    async def test_list_images_with_hashes_raises_storage_error(
        self, storage_with_mock_client: DropboxStorage
    ) -> None:
        """Verify list_images_with_hashes wraps ApiError in StorageError."""
        storage_with_mock_client.client.files_list_folder.side_effect = _create_api_error()
        
        with pytest.raises(StorageError, match="Failed to list images with hashes"):
            await storage_with_mock_client.list_images_with_hashes("/Photos")


class TestDownloadImageErrorHandling:
    """Tests for download_image exception handling (lines 190-191)."""
    
    @pytest.mark.asyncio
    async def test_download_image_raises_storage_error(
        self, storage_with_mock_client: DropboxStorage
    ) -> None:
        """Verify download_image wraps ApiError in StorageError."""
        storage_with_mock_client.client.files_download.side_effect = _create_api_error()
        
        with pytest.raises(StorageError, match="Failed to download"):
            await storage_with_mock_client.download_image("/Photos", "image.jpg")


class TestGetTemporaryLinkErrorHandling:
    """Tests for get_temporary_link exception handling (lines 206-207)."""
    
    @pytest.mark.asyncio
    async def test_get_temporary_link_raises_storage_error(
        self, storage_with_mock_client: DropboxStorage
    ) -> None:
        """Verify get_temporary_link wraps ApiError in StorageError."""
        storage_with_mock_client.client.files_get_temporary_link.side_effect = _create_api_error()
        
        with pytest.raises(StorageError, match="Failed to get temporary link"):
            await storage_with_mock_client.get_temporary_link("/Photos", "image.jpg")


class TestEnsureFolderExistsErrorHandling:
    """Tests for ensure_folder_exists logic (lines 219-233)."""
    
    @pytest.mark.asyncio
    async def test_ensure_folder_exists_creates_folder(
        self, storage_with_mock_client: DropboxStorage
    ) -> None:
        """Verify ensure_folder_exists creates a folder successfully."""
        storage_with_mock_client.client.files_create_folder_v2.return_value = None
        
        await storage_with_mock_client.ensure_folder_exists("/Photos/keep")
        
        storage_with_mock_client.client.files_create_folder_v2.assert_called_once_with("/Photos/keep")
    
    @pytest.mark.asyncio
    async def test_ensure_folder_exists_ignores_conflict_error(
        self, storage_with_mock_client: DropboxStorage
    ) -> None:
        """Verify ensure_folder_exists ignores 'folder already exists' error."""
        class ConflictPathError:
            def is_conflict(self) -> bool:
                return True
        
        class ConflictError:
            def is_path(self) -> bool:
                return True
            def get_path(self) -> ConflictPathError:
                return ConflictPathError()
        
        conflict_exc = ApiError("req", ConflictError(), "conflict", "en")
        storage_with_mock_client.client.files_create_folder_v2.side_effect = conflict_exc
        
        # Should not raise
        await storage_with_mock_client.ensure_folder_exists("/Photos/keep")
    
    @pytest.mark.asyncio
    async def test_ensure_folder_exists_raises_on_other_errors(
        self, storage_with_mock_client: DropboxStorage
    ) -> None:
        """Verify ensure_folder_exists raises StorageError on non-conflict errors."""
        # Create an error that isn't a path conflict
        class OtherError:
            def is_path(self) -> bool:
                return False
        
        other_exc = ApiError("req", OtherError(), "other", "en")
        storage_with_mock_client.client.files_create_folder_v2.side_effect = other_exc
        
        with pytest.raises(StorageError, match="Failed to ensure folder exists"):
            await storage_with_mock_client.ensure_folder_exists("/Photos/keep")


class TestMoveImageWithSidecarsErrorHandling:
    """Tests for move_image_with_sidecars exception handling (lines 270-271)."""
    
    @pytest.mark.asyncio
    async def test_move_image_with_sidecars_raises_storage_error(
        self, storage_with_mock_client: DropboxStorage
    ) -> None:
        """Verify move_image_with_sidecars wraps ApiError in StorageError."""
        # Folder creation succeeds, but move fails
        storage_with_mock_client.client.files_create_folder_v2.return_value = None
        storage_with_mock_client.client.files_move_v2.side_effect = _create_api_error()
        
        with pytest.raises(StorageError, match="Failed to move"):
            await storage_with_mock_client.move_image_with_sidecars("/Photos", "image.jpg", "keep")
    
    @pytest.mark.asyncio
    async def test_move_image_with_sidecars_ignores_folder_exists(
        self, storage_with_mock_client: DropboxStorage
    ) -> None:
        """Verify move_image_with_sidecars ignores folder already exists error."""
        # First call (folder create) raises, second calls (moves) succeed
        storage_with_mock_client.client.files_create_folder_v2.side_effect = _create_api_error()
        storage_with_mock_client.client.files_move_v2.return_value = None
        
        # Should not raise - folder creation errors are ignored
        await storage_with_mock_client.move_image_with_sidecars("/Photos", "image.jpg", "keep")
        
        # Verify moves were called
        assert storage_with_mock_client.client.files_move_v2.call_count == 2  # image + sidecar


class TestDownloadSidecarIfExistsErrorHandling:
    """Tests for download_sidecar_if_exists error paths."""
    
    @pytest.mark.asyncio
    async def test_download_sidecar_raises_storage_error_on_non_not_found(
        self, storage_with_mock_client: DropboxStorage
    ) -> None:
        """Verify download_sidecar_if_exists wraps non-not_found ApiError in StorageError."""
        # Create an error that's NOT a "not found" error
        class OtherError:
            def is_path(self) -> bool:
                return False
        
        other_exc = ApiError("req", OtherError(), "other", "en")
        storage_with_mock_client.client.files_download.side_effect = other_exc
        
        with pytest.raises(StorageError, match="Failed to download sidecar"):
            await storage_with_mock_client.download_sidecar_if_exists("/Photos", "image.jpg")
    
    @pytest.mark.asyncio
    async def test_download_sidecar_returns_none_on_not_found(
        self, storage_with_mock_client: DropboxStorage
    ) -> None:
        """Verify download_sidecar_if_exists returns None on not_found error."""
        class NotFoundPathError:
            def is_not_found(self) -> bool:
                return True
        
        class NotFoundError:
            def is_path(self) -> bool:
                return True
            def get_path(self) -> NotFoundPathError:
                return NotFoundPathError()
        
        not_found_exc = ApiError("req", NotFoundError(), "not_found", "en")
        storage_with_mock_client.client.files_download.side_effect = not_found_exc
        
        result = await storage_with_mock_client.download_sidecar_if_exists("/Photos", "image.jpg")
        assert result is None

