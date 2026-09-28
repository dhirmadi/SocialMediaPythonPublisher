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


@pytest.mark.parametrize(
    ("root", "value", "default", "expected"),
    [
        pytest.param(
            "cloud-stage/inbox", "archive", "archive", "cloud-stage/inbox/archive", id="short-segment-under-root"
        ),
        # The orchestrator often sends full bucket-relative keys for archive/keep/remove.
        pytest.param(
            "cloud-stage/cloud-stage",
            "cloud-stage/cloud-stage/archive",
            "archive",
            "cloud-stage/cloud-stage/archive",
            id="full-prefix-not-doubled",
        ),
        pytest.param("tenant/instance", "tenant/instance/keep", "keep", "tenant/instance/keep", id="full-keep"),
        pytest.param("tenant/instance", "tenant/instance/remove", "reject", "tenant/instance/remove", id="full-remove"),
        pytest.param("/dropbox/root", "/other/archive", "archive", "/other/archive", id="leading-slash-unchanged"),
        pytest.param("a/b", None, "archive", "a/b/archive", id="default-when-none"),
        pytest.param("a/b", "   ", "archive", "a/b/archive", id="default-when-blank"),
    ],
)
def test_resolve_path(
    orch_src: OrchestratorConfigSource, root: str, value: str | None, default: str, expected: str
) -> None:
    assert orch_src._resolve_path(root, value, default) == expected


def test_resolve_path_rejects_traversal(orch_src: OrchestratorConfigSource) -> None:
    with pytest.raises(ConfigurationError):
        orch_src._resolve_path("a/b", "../x", "archive")
