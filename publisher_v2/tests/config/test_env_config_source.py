from __future__ import annotations

import pytest

from publisher_v2.config.source import EnvConfigSource
from publisher_v2.core.exceptions import TenantNotFoundError


def _minimal_env_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGE_PATHS", '{"root": "/Photos"}')
    monkeypatch.setenv("PUBLISHERS", "[]")
    monkeypatch.setenv("OPENAI_SETTINGS", "{}")
    monkeypatch.setenv("DROPBOX_APP_KEY", "test_app_key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "test_app_secret")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh_token")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-for-testing-purposes-only")


@pytest.mark.asyncio
async def test_standalone_host_rejects_other_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    _minimal_env_first(monkeypatch)
    monkeypatch.setenv("STANDALONE_HOST", "allowed.shibari.photo")
    src = EnvConfigSource()
    with pytest.raises(TenantNotFoundError):
        await src.get_config("other.shibari.photo")


@pytest.mark.asyncio
async def test_standalone_host_allows_matching_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _minimal_env_first(monkeypatch)
    monkeypatch.setenv("STANDALONE_HOST", "allowed.shibari.photo:443")
    src = EnvConfigSource()
    rc = await src.get_config("ALLOWED.SHIBARI.PHOTO")
    assert rc.host == "allowed.shibari.photo"


