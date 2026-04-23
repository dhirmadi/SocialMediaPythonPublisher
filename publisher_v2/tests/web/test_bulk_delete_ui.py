"""Tests for PUB-037: Multi-Select & Bulk Delete in Image Grid.

Verifies server-rendered HTML scaffold contains the multi-select
toggle, select-all, delete-selected button, delete queue container,
and selection counter. Client-side JS behavior is verified manually.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestMultiSelectScaffold:
    """AC-1/AC-2: Multi-select HTML elements are present."""

    def test_multi_select_toggle_button(self, managed_admin_client: TestClient) -> None:
        """Multi-select toggle button exists in grid toolbar."""
        res = managed_admin_client.get("/")
        assert res.status_code == 200
        assert 'id="grid-select-toggle"' in res.text

    def test_select_all_button(self, managed_admin_client: TestClient) -> None:
        """Select-all button exists in grid toolbar."""
        res = managed_admin_client.get("/")
        assert 'id="grid-select-all"' in res.text

    def test_delete_selected_button(self, managed_admin_client: TestClient) -> None:
        """Delete-selected button exists in grid toolbar."""
        res = managed_admin_client.get("/")
        assert 'id="grid-delete-selected"' in res.text

    def test_selection_counter(self, managed_admin_client: TestClient) -> None:
        """Selection counter span exists in grid toolbar."""
        res = managed_admin_client.get("/")
        assert 'id="grid-select-count"' in res.text

    def test_select_bar_container(self, managed_admin_client: TestClient) -> None:
        """Select bar wrapper exists and starts hidden."""
        res = managed_admin_client.get("/")
        assert 'id="grid-select-bar" class="grid-select-bar hidden"' in res.text

    def test_select_toggle_starts_hidden(self, managed_admin_client: TestClient) -> None:
        """Select toggle starts with hidden class (JS un-hides it based on feature config)."""
        res = managed_admin_client.get("/")
        assert 'id="grid-select-toggle"' in res.text
        assert "toolbar-select-toggle hidden" in res.text

    def test_delete_selected_starts_hidden(self, managed_admin_client: TestClient) -> None:
        """Delete-selected button starts hidden until selection is made."""
        res = managed_admin_client.get("/")
        assert 'id="grid-delete-selected" class="secondary danger hidden"' in res.text


class TestDeleteQueue:
    """AC-3: Delete queue container exists for bulk delete progress."""

    def test_delete_queue_container(self, managed_admin_client: TestClient) -> None:
        """Delete queue panel exists below upload queue."""
        res = managed_admin_client.get("/")
        assert 'id="delete-queue"' in res.text

    def test_delete_queue_title(self, managed_admin_client: TestClient) -> None:
        """Delete queue has a title element."""
        res = managed_admin_client.get("/")
        assert 'id="delete-queue-title"' in res.text

    def test_delete_queue_summary(self, managed_admin_client: TestClient) -> None:
        """Delete queue has a summary element for progress."""
        res = managed_admin_client.get("/")
        assert 'id="delete-queue-summary"' in res.text

    def test_delete_queue_list(self, managed_admin_client: TestClient) -> None:
        """Delete queue has a list container for per-file rows."""
        res = managed_admin_client.get("/")
        assert 'id="delete-queue-list"' in res.text

    def test_delete_queue_dismiss(self, managed_admin_client: TestClient) -> None:
        """Delete queue has a dismiss button."""
        res = managed_admin_client.get("/")
        assert 'id="delete-queue-dismiss"' in res.text

    def test_delete_queue_starts_hidden(self, managed_admin_client: TestClient) -> None:
        """Delete queue is hidden by default."""
        res = managed_admin_client.get("/")
        assert 'id="delete-queue" class="queue-panel hidden"' in res.text


class TestMultiSelectCSS:
    """CSS for multi-select mode is present."""

    def test_selected_grid_item_style(self, managed_admin_client: TestClient) -> None:
        """Selected grid items have a distinct style rule."""
        res = managed_admin_client.get("/")
        assert ".browse-grid-item.selected" in res.text

    def test_selected_hover_preserves_blue(self, managed_admin_client: TestClient) -> None:
        """Selected items keep blue border on hover (H4 fix)."""
        res = managed_admin_client.get("/")
        assert ".browse-grid-item.selected:hover" in res.text

    def test_selection_checkbox_style(self, managed_admin_client: TestClient) -> None:
        """Checkbox overlay has a style rule."""
        res = managed_admin_client.get("/")
        assert ".select-checkbox" in res.text

    def test_shared_queue_panel_style(self, managed_admin_client: TestClient) -> None:
        """Shared queue panel CSS is present (DRY refactor)."""
        res = managed_admin_client.get("/")
        assert ".queue-panel" in res.text

    def test_touch_targets_select_bar(self, managed_admin_client: TestClient) -> None:
        """Select bar buttons have min-height for touch targets."""
        res = managed_admin_client.get("/")
        assert ".grid-select-bar button" in res.text
        assert "min-height: 44px" in res.text


class TestMultiSelectJS:
    """JS functions for multi-select are present."""

    def test_toggle_multi_select_function(self, managed_admin_client: TestClient) -> None:
        """toggleMultiSelect function exists."""
        res = managed_admin_client.get("/")
        assert "function toggleMultiSelect()" in res.text

    def test_exit_multi_select_function(self, managed_admin_client: TestClient) -> None:
        """exitMultiSelect function exists."""
        res = managed_admin_client.get("/")
        assert "function exitMultiSelect()" in res.text

    def test_toggle_file_selection_function(self, managed_admin_client: TestClient) -> None:
        """toggleFileSelection function exists."""
        res = managed_admin_client.get("/")
        assert "function toggleFileSelection(fname)" in res.text

    def test_toggle_select_all_function(self, managed_admin_client: TestClient) -> None:
        """toggleSelectAll function exists."""
        res = managed_admin_client.get("/")
        assert "function toggleSelectAll()" in res.text

    def test_update_selection_ui_function(self, managed_admin_client: TestClient) -> None:
        """updateSelectionUI function exists."""
        res = managed_admin_client.get("/")
        assert "function updateSelectionUI()" in res.text

    def test_selected_files_state(self, managed_admin_client: TestClient) -> None:
        """selectedFiles Set is declared for selection state."""
        res = managed_admin_client.get("/")
        assert "let selectedFiles = new Set()" in res.text

    def test_multi_select_mode_state(self, managed_admin_client: TestClient) -> None:
        """multiSelectMode boolean is declared."""
        res = managed_admin_client.get("/")
        assert "let multiSelectMode = false" in res.text

    def test_handle_bulk_delete_function(self, managed_admin_client: TestClient) -> None:
        """handleBulkDelete function exists for executing bulk delete."""
        res = managed_admin_client.get("/")
        assert "async function handleBulkDelete()" in res.text

    def test_render_delete_queue_function(self, managed_admin_client: TestClient) -> None:
        """renderDeleteQueue function exists."""
        res = managed_admin_client.get("/")
        assert "function renderDeleteQueue()" in res.text

    def test_dismiss_delete_queue_function(self, managed_admin_client: TestClient) -> None:
        """dismissDeleteQueue function exists."""
        res = managed_admin_client.get("/")
        assert "function dismissDeleteQueue()" in res.text

    def test_retry_delete_function(self, managed_admin_client: TestClient) -> None:
        """retryDelete function exists for failed delete recovery."""
        res = managed_admin_client.get("/")
        assert "function retryDelete(index)" in res.text

    def test_escape_key_exits_multi_select(self, managed_admin_client: TestClient) -> None:
        """Escape key handler is wired to exitMultiSelect."""
        res = managed_admin_client.get("/")
        # Verify the specific Escape handler is connected to multi-select
        assert 'e.key === "Escape" && multiSelectMode' in res.text

    def test_custom_confirm_modal(self, managed_admin_client: TestClient) -> None:
        """Bulk delete uses custom modal, not native confirm()."""
        res = managed_admin_client.get("/")
        assert "function showBulkDeleteConfirm(count)" in res.text

    def test_shared_queue_renderer(self, managed_admin_client: TestClient) -> None:
        """Shared renderQueuePanel function exists (DRY)."""
        res = managed_admin_client.get("/")
        assert "function renderQueuePanel(config)" in res.text

    def test_update_result_count_function(self, managed_admin_client: TestClient) -> None:
        """Shared updateResultCount function exists (DRY)."""
        res = managed_admin_client.get("/")
        assert "function updateResultCount()" in res.text

    def test_data_filename_attribute(self, managed_admin_client: TestClient) -> None:
        """Grid items use data-filename for O(1) DOM lookup."""
        res = managed_admin_client.get("/")
        assert "item.dataset.filename = fname" in res.text

    def test_keyboard_accessibility(self, managed_admin_client: TestClient) -> None:
        """Grid items get tabindex and role in multi-select mode."""
        res = managed_admin_client.get("/")
        html = res.text
        assert 'setAttribute("tabindex", "0")' in html
        assert 'setAttribute("role", "checkbox")' in html
        assert 'setAttribute("aria-checked"' in html
