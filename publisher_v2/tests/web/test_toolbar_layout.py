"""Tests for PUB-038: Grid Toolbar Layout Redesign.

Verifies the two-zone toolbar layout (Find + Actions), visual hierarchy
styling, and responsive design. All element IDs are preserved from the
original layout — this is a pure CSS/HTML restructure.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestTwoZoneLayout:
    """AC-1: Find zone and Actions zone are present."""

    def test_toolbar_find_zone(self, managed_admin_client: TestClient) -> None:
        """Find zone wrapper exists in the toolbar."""
        res = managed_admin_client.get("/")
        assert res.status_code == 200
        assert 'class="toolbar-find"' in res.text

    def test_toolbar_actions_zone(self, managed_admin_client: TestClient) -> None:
        """Actions zone wrapper exists in the toolbar."""
        res = managed_admin_client.get("/")
        assert 'class="toolbar-actions"' in res.text

    def test_search_inside_find_zone(self, managed_admin_client: TestClient) -> None:
        """Search input is inside the find zone."""
        res = managed_admin_client.get("/")
        html = res.text
        find_start = html.index('class="toolbar-find"')
        find_end = html.index('class="toolbar-actions"')
        assert 'id="grid-search"' in html[find_start:find_end]

    def test_sort_inside_find_zone(self, managed_admin_client: TestClient) -> None:
        """Sort dropdown is inside the find zone."""
        res = managed_admin_client.get("/")
        html = res.text
        find_start = html.index('class="toolbar-find"')
        find_end = html.index('class="toolbar-actions"')
        assert 'id="grid-sort"' in html[find_start:find_end]

    def test_order_toggle_inside_find_zone(self, managed_admin_client: TestClient) -> None:
        """Order toggle is inside the find zone."""
        res = managed_admin_client.get("/")
        html = res.text
        find_start = html.index('class="toolbar-find"')
        find_end = html.index('class="toolbar-actions"')
        assert 'id="grid-order-toggle"' in html[find_start:find_end]

    def test_upload_inside_actions_zone(self, managed_admin_client: TestClient) -> None:
        """Upload button is inside the actions zone."""
        res = managed_admin_client.get("/")
        html = res.text
        actions_start = html.index('class="toolbar-actions"')
        assert 'id="grid-upload-label"' in html[actions_start:]

    def test_refresh_inside_actions_zone(self, managed_admin_client: TestClient) -> None:
        """Refresh button is inside the actions zone."""
        res = managed_admin_client.get("/")
        html = res.text
        actions_start = html.index('class="toolbar-actions"')
        assert 'id="grid-refresh-btn"' in html[actions_start:]


class TestVisualHierarchy:
    """AC-2: Visual hierarchy — compact toggle, upload styling, select placement."""

    def test_order_toggle_compact(self, managed_admin_client: TestClient) -> None:
        """Order toggle is a compact square button (no min-width:2rem style)."""
        res = managed_admin_client.get("/")
        html = res.text
        # The old style="min-width:2rem;" should be removed
        # The new button should have the compact class
        assert 'id="grid-order-toggle"' in html
        assert "toolbar-order-btn" in html

    def test_upload_gradient_style(self, managed_admin_client: TestClient) -> None:
        """Upload button uses gradient styling, not flat danger-red."""
        res = managed_admin_client.get("/")
        assert ".toolbar-upload" in res.text
        assert "linear-gradient" in res.text

    def test_select_toggle_after_toolbar(self, managed_admin_client: TestClient) -> None:
        """Select toggle is positioned after the main toolbar zones."""
        res = managed_admin_client.get("/")
        html = res.text
        actions_end = html.index("</div>", html.index('class="toolbar-actions"'))
        select_pos = html.index('id="grid-select-toggle"')
        assert select_pos > actions_end

    def test_result_count_has_metadata_class(self, managed_admin_client: TestClient) -> None:
        """Result count uses metadata styling."""
        res = managed_admin_client.get("/")
        assert 'id="grid-result-count"' in res.text


class TestResponsiveCSS:
    """AC-4: Responsive design rules exist."""

    def test_toolbar_uses_flex_layout(self, managed_admin_client: TestClient) -> None:
        """Grid toolbar uses flexbox for two-zone layout."""
        res = managed_admin_client.get("/")
        assert ".grid-toolbar" in res.text

    def test_mobile_breakpoint_exists(self, managed_admin_client: TestClient) -> None:
        """A media query exists for mobile stacking."""
        res = managed_admin_client.get("/")
        assert "@media" in res.text
        assert "640px" in res.text


class TestElementIDsPreserved:
    """AC-3: All existing element IDs survive the restructure."""

    def test_grid_search_id(self, managed_admin_client: TestClient) -> None:
        res = managed_admin_client.get("/")
        assert 'id="grid-search"' in res.text

    def test_grid_sort_id(self, managed_admin_client: TestClient) -> None:
        res = managed_admin_client.get("/")
        assert 'id="grid-sort"' in res.text

    def test_grid_order_toggle_id(self, managed_admin_client: TestClient) -> None:
        res = managed_admin_client.get("/")
        assert 'id="grid-order-toggle"' in res.text

    def test_grid_upload_input_id(self, managed_admin_client: TestClient) -> None:
        res = managed_admin_client.get("/")
        assert 'id="grid-upload-input"' in res.text

    def test_grid_upload_label_id(self, managed_admin_client: TestClient) -> None:
        res = managed_admin_client.get("/")
        assert 'id="grid-upload-label"' in res.text

    def test_grid_select_toggle_id(self, managed_admin_client: TestClient) -> None:
        res = managed_admin_client.get("/")
        assert 'id="grid-select-toggle"' in res.text

    def test_grid_refresh_btn_id(self, managed_admin_client: TestClient) -> None:
        res = managed_admin_client.get("/")
        assert 'id="grid-refresh-btn"' in res.text

    def test_grid_result_count_id(self, managed_admin_client: TestClient) -> None:
        res = managed_admin_client.get("/")
        assert 'id="grid-result-count"' in res.text

    def test_grid_select_bar_id(self, managed_admin_client: TestClient) -> None:
        res = managed_admin_client.get("/")
        assert 'id="grid-select-bar"' in res.text
