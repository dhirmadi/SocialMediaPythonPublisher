"""REL-7/PERF-5 (#88): Dropbox SDK exceptions map to StorageError, one retry layer."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from dropbox.exceptions import AuthError, BadInputError, InternalServerError, RateLimitError

from publisher_v2.config.schema import DropboxConfig
from publisher_v2.core.exceptions import StorageAuthError, StorageError
from publisher_v2.services.storage import DropboxStorage, _dropbox_wait, _is_retryable_dropbox_error


def _storage() -> DropboxStorage:
    cfg = DropboxConfig(app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos")
    storage = DropboxStorage.__new__(DropboxStorage)
    storage.config = cfg
    storage.client = MagicMock()
    return storage


class TestExceptionMapping:
    async def test_auth_error_maps_to_storage_auth_error(self) -> None:
        storage = _storage()
        storage.client.files_download.side_effect = AuthError("rid", "expired_access_token")
        with pytest.raises(StorageAuthError, match="dropbox auth failed"):
            await storage.download_image("/Photos", "a.jpg")

    async def test_bad_input_maps_to_storage_error(self) -> None:
        storage = _storage()
        storage.client.files_download.side_effect = BadInputError("rid", "bad input")
        with pytest.raises(StorageError):
            await storage.download_image("/Photos", "a.jpg")

    async def test_no_raw_dropbox_exception_escapes(self) -> None:
        storage = _storage()
        storage.client.files_download.side_effect = InternalServerError("rid", 500, "boom")
        with pytest.raises(StorageError):
            await storage.download_image("/Photos", "a.jpg")


class TestRetryability:
    def test_auth_error_not_retryable(self) -> None:
        assert _is_retryable_dropbox_error(AuthError("rid", "x")) is False
        wrapped = StorageAuthError("dropbox auth failed")
        wrapped.__cause__ = AuthError("rid", "x")
        assert _is_retryable_dropbox_error(wrapped) is False

    def test_bad_input_not_retryable(self) -> None:
        assert _is_retryable_dropbox_error(BadInputError("rid", "x")) is False

    def test_rate_limit_and_5xx_retryable(self) -> None:
        assert _is_retryable_dropbox_error(RateLimitError("rid", backoff=2)) is True
        assert _is_retryable_dropbox_error(InternalServerError("rid", 500, "b")) is True

    def test_wrapped_cause_is_unwrapped(self) -> None:
        wrapped = StorageError("failed")
        wrapped.__cause__ = InternalServerError("rid", 503, "b")
        assert _is_retryable_dropbox_error(wrapped) is True

    def test_rate_limit_backoff_drives_wait(self) -> None:
        outcome = MagicMock()
        exc = StorageError("rate limited")
        exc.__cause__ = RateLimitError("rid", backoff=2)
        outcome.exception.return_value = exc
        retry_state = MagicMock(outcome=outcome, attempt_number=1)
        assert _dropbox_wait(retry_state) == 2.0

    def test_wait_falls_back_to_exponential(self) -> None:
        outcome = MagicMock()
        exc = StorageError("boom")
        exc.__cause__ = InternalServerError("rid", 500, "b")
        outcome.exception.return_value = exc
        retry_state = MagicMock(outcome=outcome, attempt_number=1)
        assert _dropbox_wait(retry_state) >= 0


class TestRetryCount:
    async def test_internal_server_error_attempts_exactly_three(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Collapse waits so the test is fast.
        monkeypatch.setattr("publisher_v2.services.storage._dropbox_wait", lambda rs: 0.0)
        storage = _storage()
        storage.client.files_download.side_effect = InternalServerError("rid", 500, "boom")
        with pytest.raises(StorageError):
            await storage.download_image("/Photos", "a.jpg")
        assert storage.client.files_download.call_count == 3


class TestClientConstruction:
    def test_client_built_with_timeout_and_no_sdk_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def _fake_dropbox(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr("publisher_v2.services.storage.dropbox.Dropbox", _fake_dropbox)
        DropboxStorage(DropboxConfig(app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos"))
        assert captured.get("timeout") == 30
        assert captured.get("max_retries_on_error") == 0
