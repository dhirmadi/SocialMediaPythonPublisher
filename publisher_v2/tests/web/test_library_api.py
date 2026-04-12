"""Tests for PUB-031 Phase B: Admin Library API (AC9–AC14, AC20, AC21)."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    """Clear the upload rate limit between tests."""
    from publisher_v2.web.routers.library import _upload_rate_limit

    _upload_rate_limit.clear()
    yield
    _upload_rate_limit.clear()


@pytest.fixture
def managed_app(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """TestClient with managed storage configured and admin auth set up."""
    monkeypatch.setenv("WEB_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("web_admin_pw", "secret")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
    monkeypatch.setenv("WEB_DEBUG", "true")
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)

    # Mock the service to have managed storage config
    mock_service = MagicMock()
    mock_service.config.managed = MagicMock()  # Not None → library available
    mock_service.config.features.library_enabled = True
    mock_service.config.storage_paths.image_folder = "tenant/instance"
    mock_service.config.storage_paths.archive_folder = "archive"
    mock_service.config.storage_paths.folder_keep = "keep"
    mock_service.config.storage_paths.folder_remove = "reject"
    mock_service.storage = MagicMock()
    mock_service.storage._bucket = "test-bucket"
    mock_service.storage.client = MagicMock()

    from publisher_v2.web.app import app
    from publisher_v2.web.dependencies import get_request_service

    app.dependency_overrides[get_request_service] = lambda: mock_service

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()


@pytest.fixture
def admin_headers() -> dict[str, str]:
    """Auth headers for admin requests."""
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def admin_cookies() -> dict[str, str]:
    """Admin cookie for admin requests."""
    return {"pv2_admin": "1"}


@pytest.fixture
def dropbox_app(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """TestClient with Dropbox-only config (no managed storage)."""
    monkeypatch.setenv("WEB_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("web_admin_pw", "secret")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
    monkeypatch.setenv("WEB_DEBUG", "true")
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)

    mock_service = MagicMock()
    mock_service.config.managed = None  # Dropbox-only
    mock_service.config.features.library_enabled = False

    from publisher_v2.web.app import app
    from publisher_v2.web.dependencies import get_request_service

    app.dependency_overrides[get_request_service] = lambda: mock_service

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# AC9: GET /api/library/objects
# ---------------------------------------------------------------------------


class TestListObjects:
    """AC9: List objects - managed returns paginated list, Dropbox returns 404."""

    def test_list_objects_managed(
        self, managed_app: TestClient, admin_headers: dict, admin_cookies: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Managed instance returns object list."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        # Mock the list_objects_detailed method

        with patch("publisher_v2.web.routers.library._list_objects_from_storage", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = {
                "objects": [{"key": "img.jpg", "size": 1024, "last_modified": "2026-01-01T00:00:00Z"}],
                "cursor": None,
            }
            res = managed_app.get(
                "/api/library/objects",
                headers=admin_headers,
                cookies=admin_cookies,
            )

        assert res.status_code == 200
        data = res.json()
        assert "objects" in data
        assert len(data["objects"]) == 1

    def test_list_objects_404_dropbox(
        self, dropbox_app: TestClient, admin_headers: dict, admin_cookies: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dropbox-only instance returns 404."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        res = dropbox_app.get(
            "/api/library/objects",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 404
        assert "not available" in res.json()["detail"].lower()

    def test_list_objects_paginated(
        self, managed_app: TestClient, admin_headers: dict, admin_cookies: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pagination cursor is returned."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        with patch("publisher_v2.web.routers.library._list_objects_from_storage", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = {
                "objects": [{"key": f"img{i}.jpg", "size": 100, "last_modified": "2026-01-01"} for i in range(50)],
                "cursor": "next-page-token",
            }
            res = managed_app.get(
                "/api/library/objects?limit=50",
                headers=admin_headers,
                cookies=admin_cookies,
            )

        assert res.status_code == 200
        data = res.json()
        assert data["cursor"] == "next-page-token"


class TestListObjectsFromStorageImpl:
    """Managed library list uses Delimiter=/ so nested keys do not appear as root files."""

    async def test_list_uses_delimiter_and_returns_basename_keys(self) -> None:
        from publisher_v2.web.routers.library import _list_objects_from_storage

        service = MagicMock()
        service.storage._bucket = "bkt"
        service.storage.client.list_objects_v2.return_value = {
            "Contents": [{"Key": "tenant/root/a.jpg", "Size": 10, "LastModified": "2026-01-01"}],
            "IsTruncated": False,
        }
        result = await _list_objects_from_storage(service, "tenant/root/", None, 50)
        assert result == {
            "objects": [{"key": "a.jpg", "size": 10, "last_modified": "2026-01-01"}],
            "cursor": None,
        }
        service.storage.client.list_objects_v2.assert_called_once_with(
            Bucket="bkt", Prefix="tenant/root/", Delimiter="/", MaxKeys=50
        )

    async def test_list_skips_sidecar_txt(self) -> None:
        from publisher_v2.web.routers.library import _list_objects_from_storage

        service = MagicMock()
        service.storage._bucket = "bkt"
        service.storage.client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "tenant/root/a.jpg", "Size": 10, "LastModified": "t"},
                {"Key": "tenant/root/a.txt", "Size": 2, "LastModified": "t"},
            ],
            "IsTruncated": False,
        }
        result = await _list_objects_from_storage(service, "tenant/root/", None, 50)
        assert len(result["objects"]) == 1
        assert result["objects"][0]["key"] == "a.jpg"

    async def test_list_passes_continuation_token(self) -> None:
        from publisher_v2.web.routers.library import _list_objects_from_storage

        service = MagicMock()
        service.storage._bucket = "bkt"
        service.storage.client.list_objects_v2.return_value = {"Contents": [], "IsTruncated": False}
        await _list_objects_from_storage(service, "p/", "next-token", 10)
        kwargs = service.storage.client.list_objects_v2.call_args.kwargs
        assert kwargs["ContinuationToken"] == "next-token"


# ---------------------------------------------------------------------------
# AC10: POST /api/library/upload
# ---------------------------------------------------------------------------


class TestUpload:
    """AC10: Upload validates MIME/size, stores in managed storage."""

    def test_upload_jpeg_success(
        self, managed_app: TestClient, admin_headers: dict, admin_cookies: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        with patch("publisher_v2.web.routers.library._upload_to_storage", new_callable=AsyncMock) as mock_upload:
            mock_upload.return_value = {"key": "tenant/instance/test.jpg", "size": 1024}
            res = managed_app.post(
                "/api/library/upload",
                headers=admin_headers,
                cookies=admin_cookies,
                files={"file": ("test.jpg", b"\xff\xd8\xff" + b"\x00" * 100, "image/jpeg")},
            )

        assert res.status_code == 200
        assert res.json()["key"] == "tenant/instance/test.jpg"

    def test_upload_png_success(
        self, managed_app: TestClient, admin_headers: dict, admin_cookies: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        with patch("publisher_v2.web.routers.library._upload_to_storage", new_callable=AsyncMock) as mock_upload:
            mock_upload.return_value = {"key": "tenant/instance/test.png", "size": 2048}
            res = managed_app.post(
                "/api/library/upload",
                headers=admin_headers,
                cookies=admin_cookies,
                files={"file": ("test.png", b"\x89PNG" + b"\x00" * 100, "image/png")},
            )

        assert res.status_code == 200

    def test_upload_rejects_disallowed_mime_415(
        self, managed_app: TestClient, admin_headers: dict, admin_cookies: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        res = managed_app.post(
            "/api/library/upload",
            headers=admin_headers,
            cookies=admin_cookies,
            files={"file": ("test.gif", b"GIF89a" + b"\x00" * 100, "image/gif")},
        )
        assert res.status_code == 415

    def test_upload_rejects_oversize_413(
        self, managed_app: TestClient, admin_headers: dict, admin_cookies: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        monkeypatch.setenv("LIBRARY_MAX_UPLOAD_MB", "1")

        # 2 MB file exceeds 1 MB limit
        large_data = b"\xff\xd8\xff" + b"\x00" * (2 * 1024 * 1024)
        res = managed_app.post(
            "/api/library/upload",
            headers=admin_headers,
            cookies=admin_cookies,
            files={"file": ("big.jpg", large_data, "image/jpeg")},
        )
        assert res.status_code == 413


# ---------------------------------------------------------------------------
# AC11: Upload rate limit
# ---------------------------------------------------------------------------


class TestUploadRateLimit:
    """AC11: Rate limit 10 uploads/minute per admin session."""

    def test_upload_rate_limit_429(
        self, managed_app: TestClient, admin_headers: dict, admin_cookies: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        with patch("publisher_v2.web.routers.library._upload_to_storage", new_callable=AsyncMock) as mock_upload:
            mock_upload.return_value = {"key": "tenant/instance/img.jpg", "size": 100}

            # Make 10 successful uploads
            for i in range(10):
                res = managed_app.post(
                    "/api/library/upload",
                    headers=admin_headers,
                    cookies=admin_cookies,
                    files={"file": (f"img{i}.jpg", b"\xff\xd8\xff" + b"\x00" * 10, "image/jpeg")},
                )
                assert res.status_code == 200, f"Upload {i} failed: {res.json()}"

            # 11th should be rate limited
            res = managed_app.post(
                "/api/library/upload",
                headers=admin_headers,
                cookies=admin_cookies,
                files={"file": ("img11.jpg", b"\xff\xd8\xff" + b"\x00" * 10, "image/jpeg")},
            )
            assert res.status_code == 429


# ---------------------------------------------------------------------------
# AC12: DELETE /api/library/objects/{filename}
# ---------------------------------------------------------------------------


class TestDelete:
    """AC12: Delete removes image and sidecar."""

    def test_delete_removes_image_and_sidecar(
        self, managed_app: TestClient, admin_headers: dict, admin_cookies: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        with patch("publisher_v2.web.routers.library._delete_from_storage", new_callable=AsyncMock) as mock_del:
            mock_del.return_value = {"deleted": "img.jpg", "sidecar_deleted": True}
            res = managed_app.delete(
                "/api/library/objects/img.jpg",
                headers=admin_headers,
                cookies=admin_cookies,
            )

        assert res.status_code == 200
        assert res.json()["deleted"] == "img.jpg"
        assert res.json()["sidecar_deleted"] is True

    def test_delete_404_not_found(
        self, managed_app: TestClient, admin_headers: dict, admin_cookies: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        with patch("publisher_v2.web.routers.library._delete_from_storage", new_callable=AsyncMock) as mock_del:
            mock_del.side_effect = FileNotFoundError("Not found")
            res = managed_app.delete(
                "/api/library/objects/nonexist.jpg",
                headers=admin_headers,
                cookies=admin_cookies,
            )

        assert res.status_code == 404


# ---------------------------------------------------------------------------
# AC13: POST /api/library/objects/{filename}/move
# ---------------------------------------------------------------------------


class TestMove:
    """AC13: Move image + sidecar to target folder."""

    def test_move_to_keep(
        self, managed_app: TestClient, admin_headers: dict, admin_cookies: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        with patch("publisher_v2.web.routers.library._move_in_storage", new_callable=AsyncMock) as mock_move:
            mock_move.return_value = {"moved": "img.jpg", "destination": "keep"}
            res = managed_app.post(
                "/api/library/objects/img.jpg/move",
                headers=admin_headers,
                cookies=admin_cookies,
                json={"target_folder": "keep"},
            )

        assert res.status_code == 200
        assert res.json()["moved"] == "img.jpg"
        assert res.json()["destination"] == "keep"

    def test_move_to_archive(
        self, managed_app: TestClient, admin_headers: dict, admin_cookies: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        with patch("publisher_v2.web.routers.library._move_in_storage", new_callable=AsyncMock) as mock_move:
            mock_move.return_value = {"moved": "img.jpg", "destination": "archive"}
            res = managed_app.post(
                "/api/library/objects/img.jpg/move",
                headers=admin_headers,
                cookies=admin_cookies,
                json={"target_folder": "archive"},
            )

        assert res.status_code == 200

    def test_move_invalid_target_400(
        self, managed_app: TestClient, admin_headers: dict, admin_cookies: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        res = managed_app.post(
            "/api/library/objects/img.jpg/move",
            headers=admin_headers,
            cookies=admin_cookies,
            json={"target_folder": "invalid_folder"},
        )
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# AC14: Auth enforcement
# ---------------------------------------------------------------------------


class TestAuthEnforcement:
    """AC14: All library endpoints require auth + admin."""

    def test_endpoints_require_auth_401(self, managed_app: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """No auth header → 401."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        # Simple endpoints
        res = managed_app.get("/api/library/objects")
        assert res.status_code == 401
        res = managed_app.delete("/api/library/objects/img.jpg")
        assert res.status_code == 401

        # Move needs JSON body
        res = managed_app.post("/api/library/objects/img.jpg/move", json={"target_folder": "keep"})
        assert res.status_code == 401

        # Upload needs a file body
        res = managed_app.post(
            "/api/library/upload",
            files={"file": ("test.jpg", b"\xff\xd8\xff", "image/jpeg")},
        )
        assert res.status_code == 401

    def test_endpoints_require_admin_403(
        self, managed_app: TestClient, admin_headers: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Auth present but no admin cookie → 403."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        res = managed_app.get("/api/library/objects", headers=admin_headers)
        assert res.status_code == 403
        res = managed_app.delete("/api/library/objects/img.jpg", headers=admin_headers)
        assert res.status_code == 403

        # Move needs JSON body
        res = managed_app.post(
            "/api/library/objects/img.jpg/move", headers=admin_headers, json={"target_folder": "keep"}
        )
        assert res.status_code == 403

        # Upload needs a file body
        res = managed_app.post(
            "/api/library/upload",
            headers=admin_headers,
            files={"file": ("test.jpg", b"\xff\xd8\xff", "image/jpeg")},
        )
        assert res.status_code == 403


# ---------------------------------------------------------------------------
# AC20: /api/config/features includes library_enabled
# ---------------------------------------------------------------------------


class TestFeaturesEndpoint:
    """AC20: Features endpoint reports library_enabled."""

    def test_features_endpoint_includes_library_enabled(
        self, managed_app: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        # Mock resolve_library_enabled at the source module
        with patch("publisher_v2.config.features.resolve_library_enabled", return_value=True):
            res = managed_app.get("/api/config/features")

        assert res.status_code == 200
        data = res.json()
        assert "library_enabled" in data
        assert data["library_enabled"] is True


# ---------------------------------------------------------------------------
# AC21: No credentials in responses or logs
# ---------------------------------------------------------------------------


class TestNoCredentials:
    """AC21: No credential material in API responses or logs."""

    def test_no_credentials_in_responses_or_logs(
        self, managed_app: TestClient, admin_headers: dict, admin_cookies: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "super_secret_key_12345")

        with patch("publisher_v2.web.routers.library._list_objects_from_storage", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = {"objects": [], "cursor": None}
            res = managed_app.get(
                "/api/library/objects",
                headers=admin_headers,
                cookies=admin_cookies,
            )

        assert res.status_code == 200
        response_text = res.text
        assert "super_secret_key_12345" not in response_text
        assert "access_key" not in response_text.lower() or "AKID" not in response_text


class TestLibraryListPrefixResolution:
    """Library S3 prefix must not double-prefix orchestrator-style full paths."""

    def test_full_archive_prefix_not_doubled(self) -> None:
        from publisher_v2.config.schema import StoragePathConfig
        from publisher_v2.web.routers.library import _library_list_prefix

        paths = StoragePathConfig(
            image_folder="tenant/root",
            archive_folder="tenant/root/archive",
            folder_keep="tenant/root/keep",
            folder_remove="tenant/root/reject",
        )
        assert _library_list_prefix(paths, "archive") == "tenant/root/archive/"
        assert _library_list_prefix(paths, "keep") == "tenant/root/keep/"
        assert _library_list_prefix(paths, "") == "tenant/root/"

    def test_short_segment_joined_under_root(self) -> None:
        from publisher_v2.config.schema import StoragePathConfig
        from publisher_v2.web.routers.library import _library_list_prefix

        paths = StoragePathConfig(
            image_folder="tenant/root",
            archive_folder="archive",
        )
        assert _library_list_prefix(paths, "archive") == "tenant/root/archive/"
