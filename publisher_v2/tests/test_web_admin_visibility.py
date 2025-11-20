from __future__ import annotations

from fastapi.testclient import TestClient

from publisher_v2.web.app import app


def _get_index_html() -> str:
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200
    return res.text


def test_admin_sections_hidden_for_non_admin() -> None:
    html = _get_index_html()
    # Admin-only panels and controls should be present but initially hidden
    assert 'id="panel-admin"' in html
    assert 'id="panel-activity"' in html
    assert 'id="admin-controls"' in html
    # Hidden marker class should be applied so non-admin users do not see them
    assert 'class="panel admin-only hidden" id="panel-admin"' in html
    assert 'class="panel admin-only hidden" id="panel-activity"' in html


def test_activity_panel_present_and_named() -> None:
    html = _get_index_html()
    assert "<h2>Activity</h2>" in html
    # Activity area should use a single status element for the current/latest action
    assert 'id="status"' in html


def test_admin_js_contracts_present() -> None:
    html = _get_index_html()
    # Ensure the JS helpers for admin state and layout exist
    assert "function initLayout()" in html
    assert "function initAdminControls()" in html
    assert "async function fetchAdminStatus()" in html
    assert "function updateAdminState(admin)" in html


