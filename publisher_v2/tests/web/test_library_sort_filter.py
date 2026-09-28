"""Tests for PUB-032: Admin Library Sorting & Filtering (AC1–AC20)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from publisher_v2.config.runtime_settings import load_runtime_settings

# ---------------------------------------------------------------------------
# Fixtures (managed_app, library_service, admin_headers, admin_cookies: tests/web/conftest.py)
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.usefixtures("_clear_rate_limit")


def _make_s3_object(key: str, size: int, last_modified: datetime | str) -> dict:
    """Create a mock S3 object dict."""
    return {
        "Key": key,
        "Size": size,
        "LastModified": last_modified if isinstance(last_modified, datetime) else last_modified,
    }


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


def _setup_s3_list(library_service: MagicMock, objects: list[dict], is_truncated: bool = False) -> None:
    """#96: the router now uses only the storage protocol — fake list_objects."""

    page = {
        "items": [
            {"key": obj["Key"], "size": obj.get("Size", 0), "last_modified": obj.get("LastModified")} for obj in objects
        ],
        "cursor": "next-token" if is_truncated else None,
        "is_truncated": is_truncated,
    }
    library_service.storage.list_objects = AsyncMock(return_value=page)


# ---------------------------------------------------------------------------
# AC1-AC3, AC14: sort by name / last_modified / size, both orders; no params = name asc
# ---------------------------------------------------------------------------


class TestSort:
    # SAMPLE_S3_OBJECTS: alpha < bravo_sunset < charlie < delta by name, by DT1..DT4 and by 1000..4000 bytes.
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            pytest.param(
                "?sort=name&order=asc",
                ["alpha.png", "bravo_sunset.jpg", "charlie.jpg", "delta.jpeg"],
                id="AC1-name-asc",
            ),
            pytest.param(
                "?sort=name&order=desc", ["delta.jpeg", "charlie.jpg", "bravo_sunset.jpg", "alpha.png"], id="name-desc"
            ),
            pytest.param(
                "?sort=last_modified&order=desc",
                ["delta.jpeg", "charlie.jpg", "bravo_sunset.jpg", "alpha.png"],
                id="AC2-last-modified-desc-newest-first",
            ),
            pytest.param(
                "?sort=last_modified&order=asc",
                ["alpha.png", "bravo_sunset.jpg", "charlie.jpg", "delta.jpeg"],
                id="last-modified-asc-oldest-first",
            ),
            pytest.param(
                "?sort=size&order=asc",
                ["alpha.png", "bravo_sunset.jpg", "charlie.jpg", "delta.jpeg"],
                id="AC3-size-asc-smallest-first",
            ),
            pytest.param(
                "?sort=size&order=desc",
                ["delta.jpeg", "charlie.jpg", "bravo_sunset.jpg", "alpha.png"],
                id="size-desc-largest-first",
            ),
            pytest.param(
                "", ["alpha.png", "bravo_sunset.jpg", "charlie.jpg", "delta.jpeg"], id="AC14-no-params-name-asc"
            ),
        ],
    )
    def test_sort_orders_objects(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        library_service: MagicMock,
        query: str,
        expected: list[str],
    ) -> None:
        """sort/order order the objects by lowercase basename, last_modified or size."""
        _setup_s3_list(library_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            f"/api/library/objects{query}",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        names = [obj["key"] for obj in res.json()["objects"]]
        assert names == expected


# ---------------------------------------------------------------------------
# AC4: Invalid sort/order returns 400
# ---------------------------------------------------------------------------


class TestInvalidParams:
    @pytest.mark.parametrize(
        "url",
        [
            pytest.param("/api/library/objects?sort=invalid", id="invalid_sort_returns_400"),
            pytest.param("/api/library/objects?order=invalid", id="invalid_order_returns_400"),
        ],
    )
    def test_invalid_param_returns_400(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        url,
    ) -> None:
        """AC4: sort=invalid or order=invalid returns 400."""
        res = managed_app.get(
            url,
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 400
        assert "detail" in res.json()


# ---------------------------------------------------------------------------
# AC5-AC7, AC10: filter by q (substring, case-insensitive, sanitised), empty results
# ---------------------------------------------------------------------------


class TestFilterQ:
    @pytest.mark.parametrize(
        ("q", "expected"),
        [
            pytest.param("sunset", ["bravo_sunset.jpg"], id="AC5-substring-match"),
            pytest.param("ALPHA", ["alpha.png"], id="AC5-case-insensitive"),
            # AC7: /, \\ and .. are stripped and the cleaned substring is used: "../alpha" -> "alpha".
            pytest.param("../alpha", ["alpha.png"], id="AC7-strips-path-traversal"),
        ],
    )
    def test_filter_q_matches_basenames(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        library_service: MagicMock,
        q: str,
        expected: list[str],
    ) -> None:
        _setup_s3_list(library_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            f"/api/library/objects?q={q}",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        names = [obj["key"] for obj in res.json()["objects"]]
        assert names == expected

    @pytest.mark.parametrize(
        "q",
        [
            pytest.param("", id="AC6-empty"),
            pytest.param("%20%20", id="AC6-whitespace-only"),
            pytest.param("/../", id="AC7-empty-after-strip"),
        ],
    )
    def test_filter_q_blank_returns_all(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        library_service: MagicMock,
        q: str,
    ) -> None:
        """A q that is empty, whitespace or empty once sanitised is no filter at all."""
        _setup_s3_list(library_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            f"/api/library/objects?q={q}",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        assert len(res.json()["objects"]) == 4

    @pytest.mark.parametrize(
        ("query", "total_in_window"),
        [
            pytest.param("?q=nonexistent", 0, id="q-no-match"),
            pytest.param("?offset=100", 4, id="AC10-offset-beyond-total"),
        ],
    )
    def test_empty_page_is_not_an_error(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        library_service: MagicMock,
        query: str,
        total_in_window: int,
    ) -> None:
        """No match, or an offset past the window, returns objects:[] with the window's size."""
        _setup_s3_list(library_service, SAMPLE_S3_OBJECTS)

        res = managed_app.get(
            f"/api/library/objects{query}",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["objects"] == []
        assert data["total_in_window"] == total_in_window


# ---------------------------------------------------------------------------
# AC8: Offset pagination
# ---------------------------------------------------------------------------


class TestOffsetPagination:
    def test_offset_pagination(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        library_service: MagicMock,
    ) -> None:
        """AC8: offset=2&limit=2 skips first 2, returns next 2 (name-sorted)."""
        _setup_s3_list(library_service, SAMPLE_S3_OBJECTS)

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
        library_service: MagicMock,
    ) -> None:
        """AC8: offset=1&limit=1 returns only the second item."""
        _setup_s3_list(library_service, SAMPLE_S3_OBJECTS)

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
        library_service: MagicMock,
    ) -> None:
        """AC9: Response has total_in_window (count of all matching) and truncated (bool)."""
        _setup_s3_list(library_service, SAMPLE_S3_OBJECTS)

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
# AC11: Scan budget truncation
# ---------------------------------------------------------------------------


class TestScanBudget:
    @pytest.mark.parametrize(
        ("budget_env", "budget"),
        [
            pytest.param("2", 2, id="scan_budget_truncation"),
            pytest.param("3", 3, id="scan_budget_env_override"),
        ],
    )
    def test_scan_budget_truncates_listing(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        library_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        budget_env,
        budget,
    ) -> None:
        """AC11/AC12: when scan_budget (LIBRARY_SCAN_BUDGET overrides the default) is reached, truncated=true."""
        monkeypatch.setenv("LIBRARY_SCAN_BUDGET", budget_env)

        # S3 returns 2 objects then says IsTruncated=True (more exist)
        _setup_s3_list(library_service, SAMPLE_S3_OBJECTS[:budget], is_truncated=True)

        res = managed_app.get(
            "/api/library/objects?sort=name&order=asc",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["truncated"] is True
        assert data["total_in_window"] == budget

    def test_scan_budget_invalid_env_fallback(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        library_service: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC12: Invalid LIBRARY_SCAN_BUDGET falls back to default 5000."""
        monkeypatch.setenv("LIBRARY_SCAN_BUDGET", "not_a_number")

        _setup_s3_list(library_service, SAMPLE_S3_OBJECTS)

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
        library_service: MagicMock,
    ) -> None:
        """AC13: cursor + no new params uses legacy S3 cursor pagination."""
        _setup_s3_list(
            library_service,
            [
                {"Key": "tenant/instance/img1.jpg", "Size": 100, "LastModified": "2026-01-01T00:00:00Z"},
                {"Key": "tenant/instance/img2.jpg", "Size": 200, "LastModified": "2026-01-02T00:00:00Z"},
            ],
            is_truncated=True,
        )

        res = managed_app.get(
            "/api/library/objects?cursor=page1-token&limit=2",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["cursor"] == "next-token"  # the fake page cursor
        assert data["total_in_window"] == 0
        assert data["truncated"] is False

    def test_cursor_response_has_zero_total(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        library_service: MagicMock,
    ) -> None:
        """AC13: Legacy cursor path has total_in_window=0, truncated=False."""
        _setup_s3_list(
            library_service,
            [{"Key": "tenant/instance/img.jpg", "Size": 100, "LastModified": "2026-01-01"}],
            is_truncated=False,
        )

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
# Combined: filter + sort + pagination
# ---------------------------------------------------------------------------


class TestCombined:
    def test_filter_and_sort_combined(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        library_service: MagicMock,
    ) -> None:
        """Filter + sort works together: q=a with sort=size&order=desc."""
        # Add more objects with 'a' in name
        objects = [
            *SAMPLE_S3_OBJECTS,
            _make_s3_object("tenant/instance/amazing.jpg", 500, DT1),
        ]
        _setup_s3_list(library_service, objects)

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
        library_service: MagicMock,
    ) -> None:
        """Filter + sort + offset pagination: q=a, sort=name, offset=1, limit=2."""
        _setup_s3_list(library_service, SAMPLE_S3_OBJECTS)

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
    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param(None, id="sanitize_none"),
            pytest.param("", id="sanitize_empty"),
            pytest.param("   ", id="sanitize_whitespace_only"),
            pytest.param("/../", id="sanitize_becomes_empty_after_strip"),
        ],
    )
    def test_sanitize_blank_returns_none(self, raw) -> None:
        from publisher_v2.web.routers.library import _sanitize_filter

        assert _sanitize_filter(raw) is None

    @pytest.mark.parametrize(
        ("expected", "raw"),
        [
            pytest.param("etcpasswd", "../etc/passwd", id="sanitize_strips_slashes"),
            pytest.param("testpath", "test\\path", id="sanitize_strips_backslash"),
            pytest.param("testfile", "test\x00file", id="sanitize_strips_null_bytes"),
        ],
    )
    def test_sanitize_strips_path_characters(self, expected, raw) -> None:
        from publisher_v2.web.routers.library import _sanitize_filter

        assert _sanitize_filter(raw) == expected

    def test_sanitize_max_length(self) -> None:
        from publisher_v2.web.routers.library import _sanitize_filter

        long_q = "a" * 150
        result = _sanitize_filter(long_q)
        assert result is not None
        assert len(result) == 100


# ---------------------------------------------------------------------------
# Unit tests for _get_scan_budget
# ---------------------------------------------------------------------------


class TestGetScanBudget:
    """#143: the budget is read off the request's settings snapshot, which the
    environment feeds at process start — so these still pin the env parsing, via
    ``load_runtime_settings()`` rather than a per-call lookup inside the helper."""

    def test_default_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from publisher_v2.web.routers.library import _get_scan_budget

        monkeypatch.delenv("LIBRARY_SCAN_BUDGET", raising=False)
        assert _get_scan_budget(load_runtime_settings()) == 5000

    @pytest.mark.parametrize(
        ("env_value", "expected"),
        [
            pytest.param("1000", 1000, id="env_override"),
            pytest.param("abc", 5000, id="invalid_env_fallback"),
        ],
    )
    def test_scan_budget_env(self, monkeypatch: pytest.MonkeyPatch, env_value, expected) -> None:
        from publisher_v2.web.routers.library import _get_scan_budget

        monkeypatch.setenv("LIBRARY_SCAN_BUDGET", env_value)
        assert _get_scan_budget(load_runtime_settings()) == expected


# ---------------------------------------------------------------------------
# anchor_key: open grid on page containing a specific image
# ---------------------------------------------------------------------------

# Need more objects to span multiple pages
DT_A = datetime(2026, 1, 1, tzinfo=UTC)

MANY_S3_OBJECTS = [_make_s3_object(f"tenant/instance/img_{i:03d}.jpg", 1000 + i, DT_A) for i in range(20)]


class TestAnchorKey:
    """Grid should open on the page containing the anchor image."""

    @pytest.mark.parametrize(
        ("url", "offset", "anchor"),
        [
            pytest.param(
                "/api/library/objects?sort=name&order=asc&limit=5&anchor_key=img_015.jpg",
                15,
                "img_015.jpg",
                id="anchor_key_returns_correct_page",
            ),
            pytest.param(
                "/api/library/objects?sort=name&order=asc&limit=5&anchor_key=img_002.jpg",
                0,
                "img_002.jpg",
                id="anchor_key_first_page",
            ),
            pytest.param(
                "/api/library/objects?sort=name&order=desc&limit=5&anchor_key=img_002.jpg",
                15,
                "img_002.jpg",
                id="anchor_key_respects_sort_order",
            ),
        ],
    )
    def test_anchor_key_returns_page_containing_it(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        library_service: MagicMock,
        url,
        offset,
        anchor,
    ) -> None:
        """anchor_key returns the page holding it: page 4 (offset 15), the first page, and in desc order."""
        _setup_s3_list(library_service, MANY_S3_OBJECTS)

        res = managed_app.get(
            url,
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["anchor_offset"] == offset
        names = [obj["key"] for obj in data["objects"]]
        assert anchor in names

    @pytest.mark.parametrize(
        ("url", "first_key"),
        [
            pytest.param(
                "/api/library/objects?sort=name&order=asc&limit=5&offset=10&anchor_key=nonexistent.jpg",
                "img_010.jpg",
                id="anchor_key_not_found_keeps_offset",
            ),
            pytest.param(
                "/api/library/objects?sort=name&order=asc&limit=5&offset=5",
                "img_005.jpg",
                id="anchor_key_without_value_returns_normal_page",
            ),
        ],
    )
    def test_anchor_key_absent_keeps_offset(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        library_service: MagicMock,
        url,
        first_key,
    ) -> None:
        """An unknown or absent anchor_key leaves anchor_offset null and the caller's offset in force."""
        _setup_s3_list(library_service, MANY_S3_OBJECTS)

        res = managed_app.get(
            url,
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["anchor_offset"] is None
        names = [obj["key"] for obj in data["objects"]]
        assert names[0] == first_key

    def test_anchor_key_with_filter(
        self,
        managed_app: TestClient,
        admin_headers: dict,
        admin_cookies: dict,
        library_service: MagicMock,
    ) -> None:
        """anchor_key works correctly when combined with a search filter."""
        _setup_s3_list(library_service, MANY_S3_OBJECTS)

        # Filter to "01" matches img_010..img_019 (10 items); anchor img_015 is at index 5
        res = managed_app.get(
            "/api/library/objects?sort=name&order=asc&limit=3&q=01&anchor_key=img_015.jpg",
            headers=admin_headers,
            cookies=admin_cookies,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["anchor_offset"] is not None
        names = [obj["key"] for obj in data["objects"]]
        assert "img_015.jpg" in names
