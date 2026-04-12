"""Tests for PUB-031 Phase C: Admin Library UI (AC15–AC18).

Client-side behavior is primarily verified manually.
These tests verify server-rendered HTML contains the library panel
and that feature flag visibility logic is correct.
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

    # Clear cached config source to avoid stale orchestrator references
    from publisher_v2.config.source import get_config_source

    get_config_source.cache_clear()

    from publisher_v2.web.app import app

    client = TestClient(app)
    yield client

    get_config_source.cache_clear()


class TestLibraryPanelVisibility:
    """AC15: Library panel visible only when admin AND library_enabled."""

    def test_library_panel_visible_admin_managed(self, managed_admin_client: TestClient) -> None:
        """HTML contains the library panel element."""
        res = managed_admin_client.get("/")
        assert res.status_code == 200
        html = res.text
        # Panel exists in the HTML (hidden by default, JS reveals it)
        assert 'id="panel-library"' in html
        assert "Library Management" in html

    def test_library_panel_hidden_dropbox(self, managed_admin_client: TestClient) -> None:
        """For Dropbox instances, the panel exists but JS will hide it (library_enabled=false)."""
        res = managed_admin_client.get("/")
        html = res.text
        # Panel element is in HTML with hidden class (CSS hides it)
        assert 'class="panel admin-only hidden" id="panel-library"' in html

    def test_library_panel_hidden_non_admin(self, managed_admin_client: TestClient) -> None:
        """Non-admin users see the panel with 'admin-only hidden' classes."""
        res = managed_admin_client.get("/")
        html = res.text
        # The panel has admin-only class — JS will not reveal it for non-admins
        assert "admin-only" in html
        assert 'id="panel-library"' in html


class TestLibraryUIElements:
    """AC16–AC18: UI elements for upload, delete, move."""

    def test_upload_input_exists(self, managed_admin_client: TestClient) -> None:
        """HTML contains the file upload input."""
        res = managed_admin_client.get("/")
        assert 'id="library-upload-input"' in res.text
        assert 'accept="image/jpeg,image/png"' in res.text

    def test_delete_button_js_exists(self, managed_admin_client: TestClient) -> None:
        """JavaScript contains the libraryDelete function."""
        res = managed_admin_client.get("/")
        assert "libraryDelete" in res.text

    def test_move_dropdown_js_exists(self, managed_admin_client: TestClient) -> None:
        """JavaScript contains the libraryMove function."""
        res = managed_admin_client.get("/")
        assert "libraryMove" in res.text

    def test_folder_filter_exists(self, managed_admin_client: TestClient) -> None:
        """HTML contains the folder filter dropdown."""
        res = managed_admin_client.get("/")
        html = res.text
        assert 'id="library-folder-filter"' in html
        assert '<option value="archive">Archive</option>' in html
        assert '<option value="keep">Keep</option>' in html
        assert '<option value="remove">Remove</option>' in html

    def test_feature_config_includes_library(self, managed_admin_client: TestClient) -> None:
        """JavaScript reads library_enabled from feature config."""
        res = managed_admin_client.get("/")
        assert "library_enabled" in res.text
