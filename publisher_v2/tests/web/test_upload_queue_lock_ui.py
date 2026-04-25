"""Tests for PUB-042 — Upload Queue: Lock UI During Active Uploads (GH #66).

These are server-rendered HTML/JS smoke tests, matching the pattern in
test_upload_queue_ui.py. They assert that the index template contains the
elements, CSS, and JavaScript required by the spec.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient


def _get_html(client: TestClient) -> str:
    res = client.get("/")
    assert res.status_code == 200
    return res.text


# ---------------------------------------------------------------------------
# AC-01: Status banner exists
# ---------------------------------------------------------------------------


class TestStatusBanner:
    def test_ac01_status_banner_element_present(self, managed_admin_client: TestClient) -> None:
        html = _get_html(managed_admin_client)
        assert 'id="upload-queue-status"' in html

    def test_ac01_status_banner_starts_hidden(self, managed_admin_client: TestClient) -> None:
        html = _get_html(managed_admin_client)
        # Banner has the 'hidden' class by default
        match = re.search(r'<[^>]*id="upload-queue-status"[^>]*>', html)
        assert match is not None, "status banner element not found"
        tag = match.group(0)
        assert "hidden" in tag, f"status banner should default to hidden: {tag}"

    def test_ac01_status_banner_message_text_present(self, managed_admin_client: TestClient) -> None:
        html = _get_html(managed_admin_client)
        # The literal user-visible message lives somewhere in the template/JS
        assert "Uploading" in html
        assert "please wait" in html.lower()


# ---------------------------------------------------------------------------
# AC-02 / AC-07: setUploadLockState wired into processUploadQueue
# ---------------------------------------------------------------------------


class TestLockStateFunction:
    def test_ac02_lock_function_exists(self, managed_admin_client: TestClient) -> None:
        html = _get_html(managed_admin_client)
        assert "setUploadLockState" in html

    def test_ac02_lock_called_at_start_of_processing(self, managed_admin_client: TestClient) -> None:
        html = _get_html(managed_admin_client)
        match = re.search(r"async function processUploadQueue\b.*?\n    \}", html, re.DOTALL)
        assert match, "processUploadQueue not found"
        body = match.group(0)
        assert "setUploadLockState(true)" in body, "lock must be set true at start of processing"

    def test_ac07_lock_cleared_at_end_of_processing(self, managed_admin_client: TestClient) -> None:
        html = _get_html(managed_admin_client)
        match = re.search(r"async function processUploadQueue\b.*?\n    \}", html, re.DOTALL)
        assert match, "processUploadQueue not found"
        body = match.group(0)
        assert "setUploadLockState(false)" in body, "lock must be cleared when processing completes"


# ---------------------------------------------------------------------------
# AC-03: CSS class .uploading-active toggled and styled
# ---------------------------------------------------------------------------


class TestUploadingActiveClass:
    def test_ac03_css_rule_defined(self, managed_admin_client: TestClient) -> None:
        html = _get_html(managed_admin_client)
        assert ".uploading-active" in html, "CSS rule for .uploading-active must exist"

    def test_ac03_class_toggled_on_grid_panel(self, managed_admin_client: TestClient) -> None:
        html = _get_html(managed_admin_client)
        # The setUploadLockState body should add/remove the class on the grid panel
        match = re.search(r"function setUploadLockState\b.*?\n    \}", html, re.DOTALL)
        assert match, "setUploadLockState not found"
        body = match.group(0)
        assert "uploading-active" in body
        assert "classList" in body and ("add" in body or "remove" in body or "toggle" in body)


# ---------------------------------------------------------------------------
# AC-04: Six controls disabled while locked
# ---------------------------------------------------------------------------


_LOCK_TARGETS = [
    "grid-refresh-btn",
    "grid-sort",
    "grid-order-toggle",
    "grid-search",
    "grid-select-toggle",
    "grid-delete-selected",
]


class TestControlsDisabled:
    def test_ac04_lock_targets_referenced(self, managed_admin_client: TestClient) -> None:
        html = _get_html(managed_admin_client)
        # The lock function may iterate a UPLOAD_LOCK_TARGETS constant declared
        # nearby; capture from the constant (or function start) to the function end.
        match = re.search(
            r"(?:UPLOAD_LOCK_TARGETS\b[\s\S]*?function setUploadLockState\b|function setUploadLockState\b)"
            r"[\s\S]*?\n    \}",
            html,
        )
        assert match, "setUploadLockState chain not found"
        body = match.group(0)
        for target in _LOCK_TARGETS:
            assert target in body, f"setUploadLockState chain must reference #{target}"

    def test_ac04_disabled_attribute_toggled(self, managed_admin_client: TestClient) -> None:
        html = _get_html(managed_admin_client)
        match = re.search(r"function setUploadLockState\b.*?\n    \}", html, re.DOTALL)
        assert match, "setUploadLockState not found"
        body = match.group(0)
        assert "disabled" in body, "setUploadLockState must toggle disabled attribute"


# ---------------------------------------------------------------------------
# AC-05: beforeunload listener
# ---------------------------------------------------------------------------


class TestBeforeUnloadGuard:
    def test_ac05_beforeunload_listener_added(self, managed_admin_client: TestClient) -> None:
        html = _get_html(managed_admin_client)
        match = re.search(r"function setUploadLockState\b.*?\n    \}", html, re.DOTALL)
        assert match, "setUploadLockState not found"
        body = match.group(0)
        assert "beforeunload" in body, "beforeunload listener must be wired"
        assert "addEventListener" in body and "removeEventListener" in body, (
            "beforeunload must be both added and removed by setUploadLockState"
        )


# ---------------------------------------------------------------------------
# AC-06: selectGridItem confirms before navigation while processing
# ---------------------------------------------------------------------------


class TestNavigationGuard:
    def test_ac06_select_grid_item_checks_processing(self, managed_admin_client: TestClient) -> None:
        html = _get_html(managed_admin_client)
        match = re.search(r"async function selectGridItem\b.*?\n    \}", html, re.DOTALL)
        assert match, "selectGridItem not found"
        body = match.group(0)
        assert "uploadQueueProcessing" in body, "selectGridItem must inspect uploadQueueProcessing"
        assert "confirm(" in body, "selectGridItem must show a confirmation dialog while processing"


# ---------------------------------------------------------------------------
# AC-08: Failed entries alone do not lock the UI
# ---------------------------------------------------------------------------


class TestNoLockWhenIdle:
    def test_ac08_lock_uses_processing_flag_not_failed_count(self, managed_admin_client: TestClient) -> None:
        """The lock is keyed on `uploadQueueProcessing` (false at queue end), not on
        the presence of failed entries. Verify by reading the lock function and
        confirming it does NOT key off `failed` or queue length."""
        html = _get_html(managed_admin_client)
        match = re.search(r"function setUploadLockState\b.*?\n    \}", html, re.DOTALL)
        assert match, "setUploadLockState not found"
        body = match.group(0)
        # Sanity: function takes a boolean param and uses it.
        # It must NOT inspect uploadQueue contents directly to decide locking.
        assert "uploadQueue.filter" not in body, "setUploadLockState must take a boolean — not reach into queue state"


# ---------------------------------------------------------------------------
# AC-09: No regressions to existing queue behaviors
# ---------------------------------------------------------------------------


class TestNoRegressions:
    def test_ac09_rate_limit_constant_still_present(self, managed_admin_client: TestClient) -> None:
        html = _get_html(managed_admin_client)
        assert "CLIENT_RATE_LIMIT_MAX" in html

    def test_ac09_dismiss_button_still_present(self, managed_admin_client: TestClient) -> None:
        html = _get_html(managed_admin_client)
        assert 'id="upload-queue-dismiss"' in html

    def test_ac09_auto_hide_delay_still_present(self, managed_admin_client: TestClient) -> None:
        html = _get_html(managed_admin_client)
        assert "AUTO_HIDE_DELAY_MS" in html

    def test_ac09_upload_with_retry_still_present(self, managed_admin_client: TestClient) -> None:
        html = _get_html(managed_admin_client)
        assert "uploadWithRetry" in html
