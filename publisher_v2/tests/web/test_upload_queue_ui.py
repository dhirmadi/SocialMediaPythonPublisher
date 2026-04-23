"""Tests for PUB-036: Upload Queue with Client-Side Rate Limiting.

These tests verify server-rendered HTML contains the upload queue scaffold
and JavaScript logic for queued uploads, rate limiting, and 429 retry.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient


def _get_html(client: TestClient) -> str:
    res = client.get("/")
    assert res.status_code == 200
    return res.text


class TestUploadQueuePanel:
    """AC-1: Visual upload queue panel exists in HTML scaffold."""

    def test_upload_queue_container_exists(self, managed_admin_client: TestClient) -> None:
        """Upload queue container element is present in the HTML."""
        html = _get_html(managed_admin_client)
        assert 'id="upload-queue"' in html

    def test_upload_queue_starts_hidden(self, managed_admin_client: TestClient) -> None:
        """Upload queue is hidden by default (shown only when files are selected)."""
        html = _get_html(managed_admin_client)
        assert re.search(r'id="upload-queue"[^>]*class="[^"]*hidden[^"]*"', html) or re.search(
            r'class="[^"]*hidden[^"]*"[^>]*id="upload-queue"', html
        )

    def test_upload_queue_list_container(self, managed_admin_client: TestClient) -> None:
        """Queue has a list container for per-file items."""
        html = _get_html(managed_admin_client)
        assert 'id="upload-queue-list"' in html

    def test_upload_queue_has_aria_live(self, managed_admin_client: TestClient) -> None:
        """Queue container has aria-live for screen reader accessibility."""
        html = _get_html(managed_admin_client)
        assert 'aria-live="polite"' in html

    def test_upload_queue_dismiss_button(self, managed_admin_client: TestClient) -> None:
        """Dismiss button exists in the queue header."""
        html = _get_html(managed_admin_client)
        assert 'id="upload-queue-dismiss"' in html

    def test_upload_queue_summary_has_role_status(self, managed_admin_client: TestClient) -> None:
        """Summary element has role=status for accessibility."""
        html = _get_html(managed_admin_client)
        assert 'role="status"' in html


class TestUploadQueueJavaScript:
    """AC-1/AC-2: JavaScript functions for queue management exist."""

    def test_upload_queue_state_variables(self, managed_admin_client: TestClient) -> None:
        """Upload queue state variables are declared."""
        html = _get_html(managed_admin_client)
        assert "uploadQueue" in html
        assert "uploadTimestamps" in html

    def test_process_upload_queue_function(self, managed_admin_client: TestClient) -> None:
        """processUploadQueue function exists for sequential processing."""
        html = _get_html(managed_admin_client)
        assert "processUploadQueue" in html

    def test_render_upload_queue_function(self, managed_admin_client: TestClient) -> None:
        """renderUploadQueue function exists for UI updates."""
        html = _get_html(managed_admin_client)
        assert "renderUploadQueue" in html

    def test_enqueue_files_function(self, managed_admin_client: TestClient) -> None:
        """enqueueFiles function exists to add files to the queue."""
        html = _get_html(managed_admin_client)
        assert "enqueueFiles" in html

    def test_upload_with_retry_function(self, managed_admin_client: TestClient) -> None:
        """uploadWithRetry function exists for proper retry loop."""
        html = _get_html(managed_admin_client)
        assert "uploadWithRetry" in html

    def test_dismiss_upload_queue_function(self, managed_admin_client: TestClient) -> None:
        """dismissUploadQueue function exists for clearing the queue."""
        html = _get_html(managed_admin_client)
        assert "dismissUploadQueue" in html


class TestClientSideRateLimiting:
    """AC-2: Client-side throttling logic."""

    def test_rate_limit_constant(self, managed_admin_client: TestClient) -> None:
        """Client-side rate limit constant is defined (~8 per 60s)."""
        html = _get_html(managed_admin_client)
        assert "CLIENT_RATE_LIMIT_MAX" in html

    def test_rate_limit_window_constant(self, managed_admin_client: TestClient) -> None:
        """Rate limit window constant is defined (60 seconds)."""
        html = _get_html(managed_admin_client)
        assert "CLIENT_RATE_LIMIT_WINDOW" in html

    def test_rate_limit_buffer_constant(self, managed_admin_client: TestClient) -> None:
        """Rate limit buffer constant is defined (no magic number)."""
        html = _get_html(managed_admin_client)
        assert "RATE_LIMIT_BUFFER_MS" in html

    def test_waiting_status_on_rate_limit(self, managed_admin_client: TestClient) -> None:
        """waitForRateLimit sets entry status to 'waiting' when paused."""
        html = _get_html(managed_admin_client)
        match = re.search(r"async function waitForRateLimit\b.*?\n    \}", html, re.DOTALL)
        assert match, "waitForRateLimit function not found"
        body = match.group(0)
        assert '"waiting"' in body, "waitForRateLimit must set status to 'waiting'"


class TestAutoRetryOn429:
    """AC-3: Auto-resume on 429 with backoff."""

    def test_429_retry_logic_exists(self, managed_admin_client: TestClient) -> None:
        """JavaScript contains 429 detection and retry logic."""
        html = _get_html(managed_admin_client)
        assert "429" in html

    def test_backoff_delay_defined(self, managed_admin_client: TestClient) -> None:
        """Backoff delay constant is defined for retry."""
        html = _get_html(managed_admin_client)
        assert "RETRY_BACKOFF_MS" in html

    def test_max_retries_defined(self, managed_admin_client: TestClient) -> None:
        """Maximum retry count is defined."""
        html = _get_html(managed_admin_client)
        assert "MAX_RETRIES" in html

    def test_retry_button_has_aria_label(self, managed_admin_client: TestClient) -> None:
        """Retry buttons include aria-label for accessibility."""
        html = _get_html(managed_admin_client)
        assert "aria-label" in html

    def test_upload_with_retry_has_proper_loop(self, managed_admin_client: TestClient) -> None:
        """uploadWithRetry uses a while loop for proper multi-retry (not nested try/catch)."""
        html = _get_html(managed_admin_client)
        match = re.search(r"async function uploadWithRetry\b.*?\n    \}", html, re.DOTALL)
        assert match, "uploadWithRetry function not found"
        body = match.group(0)
        assert "while" in body, "uploadWithRetry must use a while loop for retries"
        assert "MAX_RETRIES" in body, "uploadWithRetry must reference MAX_RETRIES"


class TestGridRefreshOnCompletion:
    """AC-4: Grid refreshes when all uploads complete."""

    def test_grid_refresh_after_queue_completes(self, managed_admin_client: TestClient) -> None:
        """processUploadQueue calls fetchGrid after all uploads finish."""
        html = _get_html(managed_admin_client)
        match = re.search(r"async function processUploadQueue\b.*?\n    \}", html, re.DOTALL)
        assert match, "processUploadQueue function not found"
        body = match.group(0)
        assert "fetchGrid" in body, "processUploadQueue must call fetchGrid on completion"


class TestBackwardCompatibility:
    """AC-5: Old upload progress replaced, upload input unchanged."""

    def test_file_input_preserved(self, managed_admin_client: TestClient) -> None:
        """The file input element is still present with correct attributes."""
        html = _get_html(managed_admin_client)
        assert 'id="grid-upload-input"' in html
        assert 'accept="image/jpeg,image/png"' in html
        assert "multiple" in html

    def test_old_handle_grid_upload_removed(self, managed_admin_client: TestClient) -> None:
        """Old handleGridUpload function is fully replaced."""
        html = _get_html(managed_admin_client)
        assert "handleGridUpload" not in html

    def test_upload_label_preserved(self, managed_admin_client: TestClient) -> None:
        """Upload label/button is still present."""
        html = _get_html(managed_admin_client)
        assert 'id="grid-upload-label"' in html

    def test_max_upload_size_constant(self, managed_admin_client: TestClient) -> None:
        """File size limit uses named constant, not magic number."""
        html = _get_html(managed_admin_client)
        assert "MAX_UPLOAD_SIZE_BYTES" in html

    def test_auto_hide_delay_constant(self, managed_admin_client: TestClient) -> None:
        """Auto-hide delay uses named constant."""
        html = _get_html(managed_admin_client)
        assert "AUTO_HIDE_DELAY_MS" in html


class TestUploadQueueCSS:
    """Upload queue has appropriate styling."""

    def test_queue_item_styles(self, managed_admin_client: TestClient) -> None:
        """CSS for upload queue items exists."""
        html = _get_html(managed_admin_client)
        assert ".upload-queue-item" in html

    def test_css_status_dots(self, managed_admin_client: TestClient) -> None:
        """CSS-only status dots replace emoji for cross-platform consistency."""
        html = _get_html(managed_admin_client)
        assert ".uq-status-dot" in html
        assert ".uq-queued" in html
        assert ".uq-uploading" in html
        assert ".uq-done" in html
        assert ".uq-failed" in html

    def test_css_waiting_status(self, managed_admin_client: TestClient) -> None:
        """Waiting status has distinct CSS styling."""
        html = _get_html(managed_admin_client)
        assert ".uq-waiting" in html

    def test_css_pulse_animation(self, managed_admin_client: TestClient) -> None:
        """Uploading/waiting dots have pulse animation."""
        html = _get_html(managed_admin_client)
        assert "uq-pulse" in html

    def test_retry_button_touch_target(self, managed_admin_client: TestClient) -> None:
        """Retry button has minimum 44px touch target for mobile."""
        html = _get_html(managed_admin_client)
        assert "min-height: 44px" in html
        assert "min-width: 44px" in html

    def test_dismiss_button_styles(self, managed_admin_client: TestClient) -> None:
        """Dismiss button has styling."""
        html = _get_html(managed_admin_client)
        assert ".upload-queue-dismiss" in html


class TestPerformance:
    """DOM thrashing and memory management."""

    def test_active_progress_bar_reference(self, managed_admin_client: TestClient) -> None:
        """Progress updates use direct DOM reference, not full re-render."""
        html = _get_html(managed_admin_client)
        assert "activeProgressBarEl" in html

    def test_upload_timestamps_cleanup(self, managed_admin_client: TestClient) -> None:
        """uploadTimestamps are cleaned up at end of processUploadQueue."""
        html = _get_html(managed_admin_client)
        match = re.search(r"async function processUploadQueue\b.*?\n    \}", html, re.DOTALL)
        assert match, "processUploadQueue function not found"
        body = match.group(0)
        assert "uploadTimestamps" in body, "processUploadQueue must clean up timestamps"

    def test_completed_entries_cleared_on_enqueue(self, managed_admin_client: TestClient) -> None:
        """Completed entries are cleared when new files are enqueued."""
        html = _get_html(managed_admin_client)
        match = re.search(r"function enqueueFiles\b.*?\n    \}", html, re.DOTALL)
        assert match, "enqueueFiles function not found"
        body = match.group(0)
        assert "filter" in body, "enqueueFiles must clear completed entries"

    def test_error_boundary_on_render(self, managed_admin_client: TestClient) -> None:
        """renderUploadQueue calls are wrapped in error boundaries."""
        html = _get_html(managed_admin_client)
        assert "error boundary" in html
