"""Tests for PUB-033: Unified Image Browser HTML scaffold.

These tests verify server-rendered HTML for the unified grid panel
that replaces the old #panel-library and the dynamic browse modal.
Client-side behavior is verified manually.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


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

    def test_login_cta_button(self, managed_admin_client: TestClient) -> None:
        """Login CTA button exists for logged-out users."""
        res = managed_admin_client.get("/")
        assert 'id="btn-login-cta"' in res.text

    def test_caption_panel_has_admin_class(self, managed_admin_client: TestClient) -> None:
        """Caption panel is admin-only (hidden when logged out)."""
        res = managed_admin_client.get("/")
        assert 'class="panel admin-only hidden" id="panel-caption"' in res.text


class TestRemovedJavaScript:
    """AC-D2..D5: Old JS functions and modal are removed."""

    def test_apiGetRandom_kept_for_random_workflow(self, managed_admin_client: TestClient) -> None:
        """apiGetRandom is retained: per operator request the publisher starts
        with a random image and only opens the grid when the user clicks
        "Back to grid". This supersedes the original AC-D3 removal."""
        res = managed_admin_client.get("/")
        assert "apiGetRandom" in res.text

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


class TestBackToGridPosition:
    """GH-59: Grid should open on the page containing the currently displayed image."""

    def test_back_to_grid_does_not_hardcode_offset_zero(self, managed_admin_client: TestClient) -> None:
        """backToGrid must not unconditionally reset gridOffset to 0."""
        res = managed_admin_client.get("/")
        html = res.text
        # The function must exist
        assert "backToGrid" in html
        # Extract the backToGrid function body (between 'async function backToGrid' and the next top-level function)
        import re

        match = re.search(r"async function backToGrid\(\)\s*\{(.*?)\n    \}", html, re.DOTALL)
        assert match, "backToGrid function not found"
        body = match.group(1)
        # Must NOT contain a bare 'gridOffset = 0;' as the only offset logic
        # It should calculate offset from currentFilename position
        assert "browseImageList" in body, "backToGrid should use browseImageList to find image position (Dropbox)"
        assert "GRID_PAGE_SIZE" in body, "backToGrid should calculate page offset from GRID_PAGE_SIZE"

    def test_back_to_grid_handles_empty_page_fallback(self, managed_admin_client: TestClient) -> None:
        """backToGrid should fall back to page 1 if the calculated offset yields an empty page."""
        res = managed_admin_client.get("/")
        html = res.text
        import re

        match = re.search(r"async function backToGrid\(\)\s*\{(.*?)\n    \}", html, re.DOTALL)
        assert match, "backToGrid function not found"
        body = match.group(1)
        # Should handle the case where offset is past the end (stale offset after curation)
        assert "gridImages.length === 0" in body or "gridImages.length==0" in body, (
            "backToGrid should handle empty page fallback"
        )


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
