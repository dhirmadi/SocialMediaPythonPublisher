"""REL-7/PERF-5 (#88): Dropbox SDK exception mapping and single retry layer."""

from __future__ import annotations

import json as _json
from unittest.mock import MagicMock

import pytest
import requests
from dropbox.dropbox_client import RouteErrorResult, RouteResult
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


# --- #132: no SDK-internal retry loop; one retry layer for every call ---------
#
# These go through the REAL dropbox.Dropbox client (and its
# request_json_string_with_retry loop). Only the single-attempt HTTP call
# (request_json_string) and the OAuth refresh are faked — the network boundary.


_LIST_OK = _json.dumps(
    {
        "entries": [
            {
                ".tag": "file",
                "name": "a.jpg",
                "id": "id:1",
                "client_modified": "2020-01-01T00:00:00Z",
                "server_modified": "2020-01-01T00:00:00Z",
                "rev": "0123456789",
                "size": 1,
                "path_lower": "/photos/a.jpg",
            }
        ],
        "cursor": "c",
        "has_more": False,
    }
)
_FILE_META = _json.dumps(
    {
        "name": "a.txt",
        "id": "id:2",
        "client_modified": "2020-01-01T00:00:00Z",
        "server_modified": "2020-01-01T00:00:00Z",
        "rev": "0123456789",
        "size": 7,
    }
)


def _http_response(body: bytes) -> requests.Response:
    resp = requests.Response()
    resp.status_code = 200
    resp._content = body
    return resp


def _real_client_storage(monkeypatch: pytest.MonkeyPatch, responses: list) -> tuple[DropboxStorage, dict]:
    """DropboxStorage with the real SDK client; each HTTP attempt pops the next response."""
    counts = {"http": 0, "sdk_sleeps": [], "tenacity_sleeps": []}
    storage = DropboxStorage(DropboxConfig(app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos"))

    def _attempt(*_args, **_kwargs):
        counts["http"] += 1
        item = responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    monkeypatch.setattr(storage.client, "request_json_string", _attempt)
    monkeypatch.setattr(storage.client, "check_and_refresh_access_token", lambda: None)
    monkeypatch.setattr("dropbox.dropbox_client.time.sleep", lambda s: counts["sdk_sleeps"].append(s))

    async def _fake_async_sleep(seconds: float) -> None:
        counts["tenacity_sleeps"].append(seconds)

    monkeypatch.setattr("asyncio.sleep", _fake_async_sleep)
    return storage, counts


class TestNoSdkRetryLoop:
    def test_client_built_with_no_sdk_rate_limit_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def _fake_dropbox(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr("publisher_v2.services.storage.dropbox.Dropbox", _fake_dropbox)
        DropboxStorage(DropboxConfig(app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos"))
        assert captured.get("max_retries_on_rate_limit") == 0

    async def test_rate_limit_reaches_tenacity_and_honours_backoff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        storage, counts = _real_client_storage(monkeypatch, [RateLimitError("rid", backoff=2), RouteResult(_LIST_OK)])
        assert await storage.list_images("/Photos") == ["a.jpg"]
        assert counts["http"] == 2
        assert counts["sdk_sleeps"] == [], "the SDK must not retry 429s itself"
        assert counts["tenacity_sleeps"] == [2.0]

    async def test_persistent_rate_limit_is_bounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        storage, counts = _real_client_storage(monkeypatch, [RateLimitError("rid", backoff=1) for _ in range(10)])
        with pytest.raises(StorageError):
            await storage.list_images("/Photos")
        assert counts["http"] == 3
        assert counts["sdk_sleeps"] == []
        assert counts["tenacity_sleeps"] == [1.0, 1.0]


class TestSidecarDownloadRetries:
    async def test_sidecar_download_retries_transient_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        storage, counts = _real_client_storage(
            monkeypatch,
            [
                InternalServerError("rid", 500, "boom"),
                InternalServerError("rid", 503, "boom"),
                RouteResult(_FILE_META, http_resp=_http_response(b"sidecar")),
            ],
        )
        assert await storage.download_sidecar_if_exists("/Photos", "a.jpg") == b"sidecar"
        assert counts["http"] == 3
        assert counts["sdk_sleeps"] == []

    async def test_sidecar_not_found_is_a_fast_miss(self, monkeypatch: pytest.MonkeyPatch) -> None:
        not_found = RouteErrorResult("rid", _json.dumps({"error": {".tag": "path", "path": {".tag": "not_found"}}}))
        storage, counts = _real_client_storage(monkeypatch, [not_found])
        assert await storage.download_sidecar_if_exists("/Photos", "a.jpg") is None
        assert counts["http"] == 1
        assert counts["tenacity_sleeps"] == []


class TestRealHttp429:
    """A real 429 HTTP response parsed by the SDK reaches tenacity with its (capped) backoff."""

    def _storage_with_http(self, monkeypatch: pytest.MonkeyPatch, responses: list[requests.Response]):
        counts = {"posts": 0, "sdk_sleeps": [], "tenacity_sleeps": []}
        storage = DropboxStorage(DropboxConfig(app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos"))

        def _post(*_args, **_kwargs):
            counts["posts"] += 1
            return responses.pop(0)

        monkeypatch.setattr(storage.client._session, "post", _post)
        monkeypatch.setattr(storage.client, "check_and_refresh_access_token", lambda: None)
        monkeypatch.setattr("dropbox.dropbox_client.time.sleep", lambda s: counts["sdk_sleeps"].append(s))

        async def _sleep(seconds: float) -> None:
            counts["tenacity_sleeps"].append(seconds)

        monkeypatch.setattr("asyncio.sleep", _sleep)
        return storage, counts

    @staticmethod
    def _resp(status: int, body: bytes, headers: dict[str, str] | None = None) -> requests.Response:
        resp = requests.Response()
        resp.status_code = status
        resp._content = body
        resp.headers.update({"Content-Type": "application/json", "X-Dropbox-Request-Id": "rid", **(headers or {})})
        return resp

    async def test_json_retry_after_drives_the_wait(self, monkeypatch: pytest.MonkeyPatch) -> None:
        too_many = self._resp(429, b'{"error": {"reason": {".tag": "too_many_requests"}, "retry_after": 3}}')
        storage, counts = self._storage_with_http(monkeypatch, [too_many, self._resp(200, _LIST_OK.encode())])
        assert await storage.list_images("/Photos") == ["a.jpg"]
        assert counts["posts"] == 2
        assert counts["sdk_sleeps"] == []
        assert counts["tenacity_sleeps"] == [3.0]

    async def test_huge_retry_after_is_capped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """#132: a server backoff must not hold a web request for minutes."""
        from publisher_v2.services.storage import MAX_RATE_LIMIT_BACKOFF_SECONDS

        # Non-JSON 429: the SDK reads the Retry-After header instead.
        too_many = self._resp(429, b"slow down", {"Content-Type": "text/plain", "Retry-After": "300"})
        storage, counts = self._storage_with_http(monkeypatch, [too_many, self._resp(200, _LIST_OK.encode())])
        assert await storage.list_images("/Photos") == ["a.jpg"]
        assert counts["tenacity_sleeps"] == [float(MAX_RATE_LIMIT_BACKOFF_SECONDS)]


# --- #132 review follow-up: the operator-visible trade-off must be documented ---


def test_the_rate_limit_backoff_cap_is_documented_for_operators() -> None:
    """Capping `Retry-After` is a deliberate deviation with a cost.

    Dropbox may ask for minutes; we wait at most 30s and try again, which can
    spend calls against an account that is already throttled. That trade-off
    is defensible on a web request path, but an operator debugging repeated
    429s will not find it by reading a comment in `storage.py`.
    """
    from pathlib import Path

    from publisher_v2.services.storage import MAX_RATE_LIMIT_BACKOFF_SECONDS

    repo_root = Path(__file__).resolve().parents[2]
    architecture = (repo_root / "docs_v2/03_Architecture/ARCHITECTURE.md").read_text()

    # Whitespace-insensitive: the sentence wraps in the markdown source.
    flattened = " ".join(architecture.split())
    assert f"capped at {MAX_RATE_LIMIT_BACKOFF_SECONDS} seconds" in flattened, (
        "ARCHITECTURE.md does not state the backoff cap the code enforces"
    )
    assert "Retry-After" in architecture, "ARCHITECTURE.md does not explain what is being capped"


def test_the_documented_backoff_waits_are_the_ones_tenacity_actually_computes() -> None:
    """The doc quoted an 8s ceiling that three attempts can never reach.

    That unreachable number then produced a wrong "~16s" figure for the sidecar
    path. Prose about timings drifts; pin the real values so it cannot.
    """
    from pathlib import Path

    from publisher_v2.services.storage import _EXPONENTIAL_WAIT

    class _RetryState:
        def __init__(self, attempt_number: int) -> None:
            self.attempt_number = attempt_number
            self.outcome = None
            self.idle_for = 0
            self.seconds_since_start = 0

    # Derived from the real stop condition, not hardcoded: raising
    # stop_after_attempt would make the doc's "3 attempts" and "1s then 2s"
    # false while a test pinned to (1, 2) kept passing.
    from publisher_v2.services.storage import DropboxStorage

    attempts = DropboxStorage.list_images.retry.stop.max_attempt_number
    waits = [float(_EXPONENTIAL_WAIT(_RetryState(n))) for n in range(1, attempts)]
    assert waits == [1.0, 2.0], waits

    architecture = (Path(__file__).resolve().parents[2] / "docs_v2/03_Architecture/ARCHITECTURE.md").read_text()
    assert f"{attempts} attempts" in architecture, "ARCHITECTURE.md does not state the real attempt count"
    assert "1s then 2s" in architecture, "ARCHITECTURE.md does not state the waits that actually happen"
    assert "~16s" not in architecture, "the unreachable-ceiling figure is back"
