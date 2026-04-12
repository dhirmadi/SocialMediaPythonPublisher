"""Tests for OrchestratorConfigSource._resolve_path (S3 key prefixes from orchestrator)."""

from __future__ import annotations

import pytest

from publisher_v2.config.source import OrchestratorConfigSource
from publisher_v2.core.exceptions import ConfigurationError


@pytest.fixture
def orch_src(monkeypatch: pytest.MonkeyPatch) -> OrchestratorConfigSource:
    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orchestrator.example")
    monkeypatch.setenv("ORCHESTRATOR_SERVICE_TOKEN", "test-token")
    return OrchestratorConfigSource()


def test_resolve_path_short_segment_relative_to_root(orch_src: OrchestratorConfigSource) -> None:
    assert orch_src._resolve_path("cloud-stage/inbox", "archive", "archive") == "cloud-stage/inbox/archive"


def test_resolve_path_full_prefix_already_under_root_not_doubled(orch_src: OrchestratorConfigSource) -> None:
    """Orchestrator often sends full bucket-relative keys for archive/keep/remove."""
    root = "cloud-stage/cloud-stage"
    archive = "cloud-stage/cloud-stage/archive"
    assert orch_src._resolve_path(root, archive, "archive") == archive


def test_resolve_path_full_keep_remove(orch_src: OrchestratorConfigSource) -> None:
    root = "tenant/instance"
    assert orch_src._resolve_path(root, "tenant/instance/keep", "keep") == "tenant/instance/keep"
    assert orch_src._resolve_path(root, "tenant/instance/remove", "reject") == "tenant/instance/remove"


def test_resolve_path_leading_slash_absolute_unchanged(orch_src: OrchestratorConfigSource) -> None:
    assert orch_src._resolve_path("/dropbox/root", "/other/archive", "archive") == "/other/archive"


def test_resolve_path_default_when_value_empty(orch_src: OrchestratorConfigSource) -> None:
    assert orch_src._resolve_path("a/b", None, "archive") == "a/b/archive"
    assert orch_src._resolve_path("a/b", "   ", "archive") == "a/b/archive"


def test_resolve_path_rejects_traversal(orch_src: OrchestratorConfigSource) -> None:
    with pytest.raises(ConfigurationError):
        orch_src._resolve_path("a/b", "../x", "archive")
