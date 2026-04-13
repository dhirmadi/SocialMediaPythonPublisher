"""Tests for PUB-033: Unified Image Browser HTML scaffold.

These tests verify server-rendered HTML for the unified grid panel
that replaces the old #panel-library and the dynamic browse modal.
Client-side behavior is verified manually.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def managed_admin_client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """TestClient configured for managed storage with admin."""
    monkeypatch.setenv("WEB_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("web_admin_pw", "secret")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
    monkeypatch.setenv("WEB_DEBUG", "true")
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)
    monkeypatch.setenv("CONFIG_SOURCE", "env")

    from publisher_v2.config.source import get_config_source

    get_config_source.cache_clear()

    from publisher_v2.web.app import app

    client = TestClient(app)
    yield client

    get_config_source.cache_clear()


class TestUnifiedGridPanel:
    """AC-A1: #panel-grid is a static <div> inside <main>."""

    def test_panel_grid_present(self, managed_admin_client: TestClient) -> None:
        """HTML contains the new unified grid panel."""
        res = managed_admin_client.get("/")
        assert res.status_code == 200
        assert 'id="panel-grid"' in res.text

    def test_panel_library_removed(self, managed_admin_client: TestClient) -> None:
        """Old #panel-library is fully removed (AC-D1)."""
        res = managed_admin_client.get("/")
        assert 'id="panel-library"' not in res.text

    def test_grid_toolbar_search_input(self, managed_admin_client: TestClient) -> None:
        """Search input is part of the grid toolbar (AC-C1)."""
        res = managed_admin_client.get("/")
        assert 'id="grid-search"' in res.text

    def test_grid_toolbar_sort_select(self, managed_admin_client: TestClient) -> None:
        """Sort dropdown is part of the grid toolbar (AC-C2)."""
        res = managed_admin_client.get("/")
        assert 'id="grid-sort"' in res.text

    def test_grid_toolbar_upload_input(self, managed_admin_client: TestClient) -> None:
        """Upload input is part of the grid toolbar (AC-C3)."""
        res = managed_admin_client.get("/")
        html = res.text
        assert 'id="grid-upload-input"' in html
        assert 'accept="image/jpeg,image/png"' in html

    def test_grid_pagination_bar(self, managed_admin_client: TestClient) -> None:
        """Pagination Previous/Next buttons exist (AC-A7)."""
        res = managed_admin_client.get("/")
        html = res.text
        assert 'id="grid-prev"' in html
        assert 'id="grid-next"' in html

    def test_grid_result_count(self, managed_admin_client: TestClient) -> None:
        """Result count element exists (AC-A6)."""
        res = managed_admin_client.get("/")
        assert 'id="grid-result-count"' in res.text

    def test_back_to_grid_button(self, managed_admin_client: TestClient) -> None:
        """Back-to-grid button exists for detail view (AC-B5)."""
        res = managed_admin_client.get("/")
        assert 'id="btn-back-to-grid"' in res.text


class TestRemovedJavaScript:
    """AC-D2..D5: Old JS functions and modal are removed."""

    def test_apiGetRandom_removed(self, managed_admin_client: TestClient) -> None:
        """AC-D3: apiGetRandom function is removed."""
        res = managed_admin_client.get("/")
        assert "apiGetRandom" not in res.text

    def test_showBrowseModal_removed(self, managed_admin_client: TestClient) -> None:
        """AC-D5: showBrowseModal function is removed."""
        res = managed_admin_client.get("/")
        assert "showBrowseModal" not in res.text

    def test_initReviewMode_removed(self, managed_admin_client: TestClient) -> None:
        """AC-D4: initReviewMode is removed."""
        res = managed_admin_client.get("/")
        assert "initReviewMode" not in res.text

    def test_loadReviewImage_removed(self, managed_admin_client: TestClient) -> None:
        """AC-D4: loadReviewImage is removed."""
        res = managed_admin_client.get("/")
        assert "loadReviewImage" not in res.text

    def test_libraryFetchObjects_removed(self, managed_admin_client: TestClient) -> None:
        """AC-D2: libraryFetchObjects is removed."""
        res = managed_admin_client.get("/")
        assert "libraryFetchObjects" not in res.text

    def test_libraryMove_removed(self, managed_admin_client: TestClient) -> None:
        """AC-D2: libraryMove is removed (move is a storage internal)."""
        res = managed_admin_client.get("/")
        assert "libraryMove" not in res.text


class TestPreservedJavaScript:
    """AC-D6: getPaginationRange is preserved; toast and admin systems remain."""

    def test_getPaginationRange_kept(self, managed_admin_client: TestClient) -> None:
        """AC-D6: getPaginationRange helper is reused for grid pagination."""
        res = managed_admin_client.get("/")
        assert "getPaginationRange" in res.text

    def test_storage_provider_consumed(self, managed_admin_client: TestClient) -> None:
        """The frontend reads storage_provider from /api/config/features (Story F)."""
        res = managed_admin_client.get("/")
        assert "storage_provider" in res.text
