"""Tests for PUB-032: Admin Library Sorting & Filtering (AC1–AC20)."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_s3_object(key: str, size: int, last_modified: datetime | str) -> dict:
    """Create a mock S3 object dict."""
    return {
        "Key": key,
        "Size": size,
        "LastModified": last_modified if isinstance(last_modified, datetime) else last_modified,
    }


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    """Clear the upload rate limit between tests."""
    from publisher_v2.web.routers.library import _upload_rate_limit

    _upload_rate_limit.clear()
    yield
    _upload_rate_limit.clear()


@pytest.fixture
def mock_service() -> MagicMock:
    """Shared mock service with managed storage configured."""
    svc = MagicMock()
    svc.config.managed = MagicMock()  # Not None -> library available
    svc.config.features.library_enabled = True
    svc.config.storage_paths.image_folder = "tenant/instance"
    svc.config.storage_paths.archive_folder = "archive"
    svc.config.storage_paths.folder_keep = "keep"
    svc.config.storage_paths.folder_remove = "reject"
    svc.storage = MagicMock()
    svc.storage._bucket = "test-bucket"
    svc.storage.client = MagicMock()
    return svc


@pytest.fixture
def managed_app(monkeypatch: pytest.MonkeyPatch, mock_service: MagicMock) -> Generator[TestClient, None, None]:
    """TestClient with managed storage configured and admin auth set up."""
    monkeypatch.setenv("WEB_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("web_admin_pw", "secret")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
    monkeypatch.setenv("WEB_DEBUG", "true")
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)

    from publisher_v2.web.app import app
    from publisher_v2.web.dependencies import get_request_service

    app.dependency_overrides[get_request_service] = lambda: mock_service

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def admin_cookies() -> dict[str, str]:
    return {"pv2_admin": "1"}


# Sample S3 objects for tests
DT1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
DT2 = datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)
DT3 = datetime(2026, 1, 3, 8, 0, 0, tzinfo=UTC)
DT4 = datetime(2026, 1, 4, 15, 0, 0, tzinfo=UTC)

SAMPLE_S3_OBJECTS = [
    _make_s3_object("tenant/instance/charlie.jpg", 3000, DT3),
    _make_s3_object("tenant/instance/alpha.png", 1000, DT1),
    _make_s3_object("tenant/instance/bravo_sunset.jpg", 2000, DT2),
    _make_s3_object("tenant/instance/delta.jpeg", 4000, DT4),
]


def _setup_s3_list(mock_service: MagicMock, objects: list[dict], is_truncated: bool = False) -> None:
    """Configure mock S3 list_objects_v2 to return given objects in one page."""
    mock_service.storage.client.list_objects_v2.return_value = {
        "Contents": objects,
        "IsTruncated": is_truncated,
        "NextContinuationToken": "next-token" if is_truncated else None,
    }


# ---------------------------------------------------------------------------
# AC1: Sort by name ascending
# ---------------------------------------------------------------------------


class TestSortNameAsc:
    def test_sort_name_asc(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC1: sort=name&order=asc returns objects sorted by lowercase basename ascending."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects?sort=name&order=asc",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        names = [obj["key"] for obj in res.json()["objects"]]
        assert names == ["alpha.png", "bravo_sunset.jpg", "charlie.jpg", "delta.jpeg"]

    def test_sort_name_desc(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """sort=name&order=desc returns objects sorted by lowercase basename descending."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects?sort=name&order=desc",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        names = [obj["key"] for obj in res.json()["objects"]]
        assert names == ["delta.jpeg", "charlie.jpg", "bravo_sunset.jpg", "alpha.png"]


# ---------------------------------------------------------------------------
# AC2: Sort by last_modified
# ---------------------------------------------------------------------------


class TestSortLastModified:
    def test_sort_last_modified_desc(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC2: sort=last_modified&order=desc returns newest first."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects?sort=last_modified&order=desc",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        names = [obj["key"] for obj in res.json()["objects"]]
        # DT4 > DT3 > DT2 > DT1 → delta, charlie, bravo_sunset, alpha
        assert names == ["delta.jpeg", "charlie.jpg", "bravo_sunset.jpg", "alpha.png"]

    def test_sort_last_modified_asc(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """sort=last_modified&order=asc returns oldest first."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects?sort=last_modified&order=asc",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        names = [obj["key"] for obj in res.json()["objects"]]
        assert names == ["alpha.png", "bravo_sunset.jpg", "charlie.jpg", "delta.jpeg"]


# ---------------------------------------------------------------------------
# AC3: Sort by size
# ---------------------------------------------------------------------------


class TestSortSize:
    def test_sort_size_asc(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC3: sort=size&order=asc returns smallest first."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects?sort=size&order=asc",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        names = [obj["key"] for obj in res.json()["objects"]]
        # 1000, 2000, 3000, 4000 → alpha, bravo_sunset, charlie, delta
        assert names == ["alpha.png", "bravo_sunset.jpg", "charlie.jpg", "delta.jpeg"]

    def test_sort_size_desc(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """sort=size&order=desc returns largest first."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects?sort=size&order=desc",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        names = [obj["key"] for obj in res.json()["objects"]]
        assert names == ["delta.jpeg", "charlie.jpg", "bravo_sunset.jpg", "alpha.png"]


# ---------------------------------------------------------------------------
# AC4: Invalid sort/order returns 400
# ---------------------------------------------------------------------------


class TestInvalidParams:
    def test_invalid_sort_returns_400(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC4: sort=invalid returns 400."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        res = managed_app.get(
            "/api/library/objects?sort=invalid",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 400
        assert "detail" in res.json()

    def test_invalid_order_returns_400(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC4: order=invalid returns 400."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        res = managed_app.get(
            "/api/library/objects?order=invalid",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 400
        assert "detail" in res.json()


# ---------------------------------------------------------------------------
# AC5: Filter by q (substring match)
# ---------------------------------------------------------------------------


class TestFilterQ:
    def test_filter_q_substring_match(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC5: q=sunset returns only objects whose basename contains 'sunset'."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects?q=sunset",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        names = [obj["key"] for obj in res.json()["objects"]]
        assert names == ["bravo_sunset.jpg"]

    def test_filter_q_case_insensitive(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC5: q matching is case-insensitive."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects?q=ALPHA",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        names = [obj["key"] for obj in res.json()["objects"]]
        assert names == ["alpha.png"]

    def test_filter_q_no_match(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """q with no matches returns empty objects and total_in_window=0."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects?q=nonexistent",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["objects"] == []
        assert data["total_in_window"] == 0


# ---------------------------------------------------------------------------
# AC6: Empty q treated as no filter
# ---------------------------------------------------------------------------


class TestFilterQEmpty:
    def test_filter_q_empty_returns_all(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC6: q= (empty) returns all objects."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects?q=",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        assert len(res.json()["objects"]) == 4

    def test_filter_q_whitespace_returns_all(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC6: q with only whitespace returns all objects."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects?q=%20%20",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        assert len(res.json()["objects"]) == 4


# ---------------------------------------------------------------------------
# AC7: Path traversal sanitization
# ---------------------------------------------------------------------------


class TestFilterQSanitization:
    def test_filter_q_strips_path_traversal(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC7: q containing /, \\, .. has those stripped; cleaned substring is used."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        # "../alpha" → stripped to "alpha"
        res = managed_app.get(
            "/api/library/objects?q=../alpha",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        names = [obj["key"] for obj in res.json()["objects"]]
        assert names == ["alpha.png"]

    def test_filter_q_becomes_empty_after_strip(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC7: q that becomes empty after stripping → no filter (all returned)."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        # "/../" → stripped to empty
        res = managed_app.get(
            "/api/library/objects?q=/../",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        assert len(res.json()["objects"]) == 4


# ---------------------------------------------------------------------------
# AC8: Offset pagination
# ---------------------------------------------------------------------------


class TestOffsetPagination:
    def test_offset_pagination(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC8: offset=2&limit=2 skips first 2, returns next 2 (name-sorted)."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects?offset=2&limit=2",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        data = res.json()
        names = [obj["key"] for obj in data["objects"]]
        # Sorted by name: alpha, bravo_sunset, charlie, delta → skip 2 → charlie, delta
        assert names == ["charlie.jpg", "delta.jpeg"]

    def test_offset_with_limit(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC8: offset=1&limit=1 returns only the second item."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects?offset=1&limit=1",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data["objects"]) == 1
        assert data["objects"][0]["key"] == "bravo_sunset.jpg"
        assert data["total_in_window"] == 4


# ---------------------------------------------------------------------------
# AC9: Response includes total_in_window and truncated
# ---------------------------------------------------------------------------


class TestResponseFields:
    def test_response_includes_total_in_window_and_truncated(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC9: Response has total_in_window (count of all matching) and truncated (bool)."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects?sort=name&order=asc",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["total_in_window"] == 4
        assert data["truncated"] is False


# ---------------------------------------------------------------------------
# AC10: Offset beyond total returns empty list
# ---------------------------------------------------------------------------


class TestOffsetBeyondTotal:
    def test_offset_beyond_total_returns_empty(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC10: offset >= total_in_window returns objects:[] (not an error)."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects?offset=100",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["objects"] == []
        assert data["total_in_window"] == 4


# ---------------------------------------------------------------------------
# AC11: Scan budget truncation
# ---------------------------------------------------------------------------


class TestScanBudget:
    def test_scan_budget_truncation(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC11: When scan_budget is reached, truncated=true."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        monkeypatch.setenv("LIBRARY_SCAN_BUDGET", "2")

        # S3 returns 2 objects then says IsTruncated=True (more exist)
        mock_service.storage.client.list_objects_v2.return_value = {
            "Contents": SAMPLE_S3_OBJECTS[:2],
            "IsTruncated": True,
            "NextContinuationToken": "tok",
        }

        res = managed_app.get(
            "/api/library/objects?sort=name&order=asc",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["truncated"] is True
        assert data["total_in_window"] == 2

    def test_scan_budget_env_override(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC12: LIBRARY_SCAN_BUDGET env var overrides default."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        monkeypatch.setenv("LIBRARY_SCAN_BUDGET", "3")

        # Return 3 objects, S3 says more exist
        mock_service.storage.client.list_objects_v2.return_value = {
            "Contents": SAMPLE_S3_OBJECTS[:3],
            "IsTruncated": True,
            "NextContinuationToken": "tok",
        }

        res = managed_app.get(
            "/api/library/objects?sort=name&order=asc",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["truncated"] is True
        assert data["total_in_window"] == 3

    def test_scan_budget_invalid_env_fallback(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC12: Invalid LIBRARY_SCAN_BUDGET falls back to default 5000."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        monkeypatch.setenv("LIBRARY_SCAN_BUDGET", "not_a_number")

        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects?sort=name&order=asc",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        # Should work fine with default budget (5000 >> 4 objects)
        assert len(res.json()["objects"]) == 4


# ---------------------------------------------------------------------------
# AC13: Legacy cursor path (backwards compatibility)
# ---------------------------------------------------------------------------


class TestLegacyCursorPath:
    def test_legacy_cursor_path_no_new_params(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC13: cursor + no new params uses legacy S3 cursor pagination."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        mock_service.storage.client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "tenant/instance/img1.jpg", "Size": 100, "LastModified": "2026-01-01T00:00:00Z"},
                {"Key": "tenant/instance/img2.jpg", "Size": 200, "LastModified": "2026-01-02T00:00:00Z"},
            ],
            "IsTruncated": True,
            "NextContinuationToken": "page2-token",
        }

        res = managed_app.get(
            "/api/library/objects?cursor=page1-token&limit=2",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["cursor"] == "page2-token"
        assert data["total_in_window"] == 0
        assert data["truncated"] is False

    def test_cursor_response_has_zero_total(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC13: Legacy cursor path has total_in_window=0, truncated=False."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

        mock_service.storage.client.list_objects_v2.return_value = {
            "Contents": [{"Key": "tenant/instance/img.jpg", "Size": 100, "LastModified": "2026-01-01"}],
            "IsTruncated": False,
        }

        res = managed_app.get(
            "/api/library/objects?cursor=some-token",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["total_in_window"] == 0
        assert data["truncated"] is False


# ---------------------------------------------------------------------------
# AC14: Default (no params) returns name-sorted ascending
# ---------------------------------------------------------------------------


class TestDefaultBehavior:
    def test_default_no_params_returns_name_asc(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC14: No parameters returns name-sorted ascending."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        names = [obj["key"] for obj in res.json()["objects"]]
        assert names == ["alpha.png", "bravo_sunset.jpg", "charlie.jpg", "delta.jpeg"]


# ---------------------------------------------------------------------------
# AC15–18: Web UI controls (template snapshot tests)
# ---------------------------------------------------------------------------


class TestUIControls:
    """PUB-033 moved these controls from #panel-library into #panel-grid.

    The unified grid panel now exposes search/sort/order/pagination
    via the grid-* element ids.
    """

    def test_ui_search_input_exists(self, managed_app: TestClient) -> None:
        """Grid panel has a search input."""
        res = managed_app.get("/")
        assert res.status_code == 200
        assert 'id="grid-search"' in res.text

    def test_ui_sort_controls_exist(self, managed_app: TestClient) -> None:
        """Grid panel has sort dropdown and order toggle."""
        res = managed_app.get("/")
        assert res.status_code == 200
        assert 'id="grid-sort"' in res.text
        assert 'id="grid-order-toggle"' in res.text

    def test_ui_result_count_container(self, managed_app: TestClient) -> None:
        """Grid panel has result count display element."""
        res = managed_app.get("/")
        assert res.status_code == 200
        assert 'id="grid-result-count"' in res.text

    def test_ui_prev_next_buttons(self, managed_app: TestClient) -> None:
        """Grid panel has Previous and Next pagination buttons."""
        res = managed_app.get("/")
        assert res.status_code == 200
        assert 'id="grid-prev"' in res.text
        assert 'id="grid-next"' in res.text


# ---------------------------------------------------------------------------
# Combined: filter + sort + pagination
# ---------------------------------------------------------------------------


class TestCombined:
    def test_filter_and_sort_combined(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Filter + sort works together: q=a with sort=size&order=desc."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        # Add more objects with 'a' in name
        objects = [
            *SAMPLE_S3_OBJECTS,
            _make_s3_object("tenant/instance/amazing.jpg", 500, DT1),
        ]
        _setup_s3_list(mock_service, objects)

        res = managed_app.get(
            "/api/library/objects?q=a&sort=size&order=desc",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        data = res.json()
        names = [obj["key"] for obj in data["objects"]]
        # Objects with 'a': alpha(1000), bravo_sunset(2000 - has 'a' in 'bravo'), charlie(3000 - has 'a'),
        # delta(4000 - has 'a'), amazing(500 - has 'a')
        # All have 'a' in basename! Sorted by size desc: delta(4000), charlie(3000), bravo_sunset(2000), alpha(1000), amazing(500)
        assert names == ["delta.jpeg", "charlie.jpg", "bravo_sunset.jpg", "alpha.png", "amazing.jpg"]
        assert data["total_in_window"] == 5

    def test_filter_sort_and_pagination(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        mock_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Filter + sort + offset pagination: q=a, sort=name, offset=1, limit=2."""
        monkeypatch.delenv("FEATURE_LIBRARY", raising=False)
        _setup_s3_list(mock_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            "/api/library/objects?q=a&sort=name&order=asc&offset=1&limit=2",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        data = res.json()
        # All 4 have 'a', sorted by name: alpha, bravo_sunset, charlie, delta
        # offset=1, limit=2 → bravo_sunset, charlie
        names = [obj["key"] for obj in data["objects"]]
        assert names == ["bravo_sunset.jpg", "charlie.jpg"]
        assert data["total_in_window"] == 4


# ---------------------------------------------------------------------------
# Unit tests for _sanitize_filter
# ---------------------------------------------------------------------------


class TestSanitizeFilter:
    def test_sanitize_none(self) -> None:
        from publisher_v2.web.routers.library import _sanitize_filter

        assert _sanitize_filter(None) is None

    def test_sanitize_empty(self) -> None:
        from publisher_v2.web.routers.library import _sanitize_filter

        assert _sanitize_filter("") is None

    def test_sanitize_strips_slashes(self) -> None:
        from publisher_v2.web.routers.library import _sanitize_filter

        assert _sanitize_filter("../etc/passwd") == "etcpasswd"

    def test_sanitize_strips_backslash(self) -> None:
        from publisher_v2.web.routers.library import _sanitize_filter

        assert _sanitize_filter("test\\path") == "testpath"

    def test_sanitize_strips_null_bytes(self) -> None:
        from publisher_v2.web.routers.library import _sanitize_filter

        assert _sanitize_filter("test\x00file") == "testfile"

    def test_sanitize_max_length(self) -> None:
        from publisher_v2.web.routers.library import _sanitize_filter

        long_q = "a" * 150
        result = _sanitize_filter(long_q)
        assert result is not None
        assert len(result) == 100

    def test_sanitize_whitespace_only(self) -> None:
        from publisher_v2.web.routers.library import _sanitize_filter

        assert _sanitize_filter("   ") is None

    def test_sanitize_becomes_empty_after_strip(self) -> None:
        from publisher_v2.web.routers.library import _sanitize_filter

        assert _sanitize_filter("/../") is None


# ---------------------------------------------------------------------------
# Unit tests for _get_scan_budget
# ---------------------------------------------------------------------------


class TestGetScanBudget:
    def test_default_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from publisher_v2.web.routers.library import _get_scan_budget

        monkeypatch.delenv("LIBRARY_SCAN_BUDGET", raising=False)
        assert _get_scan_budget() == 5000

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from publisher_v2.web.routers.library import _get_scan_budget

        monkeypatch.setenv("LIBRARY_SCAN_BUDGET", "1000")
        assert _get_scan_budget() == 1000

    def test_invalid_env_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from publisher_v2.web.routers.library import _get_scan_budget

        monkeypatch.setenv("LIBRARY_SCAN_BUDGET", "abc")
        assert _get_scan_budget() == 5000
