"""PUB-048 (#188) AC10: delete must operate only on image keys the listing knows.

``_delete_from_storage`` checks existence with a bare ``head_object`` and no
suffix restriction, so a raw sidecar key — or any object under the image folder
that the listing never returned — can be deleted directly.

Runs through the real ``publisher_v2.web.app.app``, the real env-first config
loader and the real ``ManagedStorage``; the fake sits at the boto3 client
boundary and records what the tool would have asked S3 to do.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

FOLDER = "/tenant/instance"
KEY_PREFIX = FOLDER.strip("/")


class _FakeS3:
    """Every key reads as present (head_object never 404s); deletes are recorded."""

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.keys: list[str] = [f"{KEY_PREFIX}/known.jpg"]

    def get_paginator(self, _name: str) -> Any:
        keys = list(self.keys)

        class _Paginator:
            def paginate(self, **_kwargs: Any) -> Any:
                return [{"Contents": [{"Key": k, "Size": 10, "LastModified": None} for k in keys]}]

        return _Paginator()

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        return {"ETag": '"e"', "ContentLength": 10, "LastModified": None}

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self.deleted.append(kwargs["Key"])
        return {}

    def close(self) -> None:
        return None


@pytest.fixture
def delete_client_and_s3(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[tuple[httpx.AsyncClient, _FakeS3]]:
    env = {
        "CONFIG_SOURCE": "env",
        "HOME": str(tmp_path),
        "STORAGE_PROVIDER": "managed",
        "R2_ACCESS_KEY_ID": "k",
        "R2_SECRET_ACCESS_KEY": "s",
        "R2_ENDPOINT_URL": "https://account.r2.cloudflarestorage.com",
        "R2_BUCKET_NAME": "bucket",
        "STORAGE_PATHS": json.dumps({"root": FOLDER, "archive": "archive", "keep": "keep", "remove": "reject"}),
        "PUBLISHERS": json.dumps([{"type": "telegram", "channel_id": "@chan"}]),
        "TELEGRAM_BOT_TOKEN": "tg",
        "OPENAI_SETTINGS": "{}",
        "OPENAI_API_KEY": "sk-test",  # pragma: allowlist secret
        "WEB_SESSION_SECRET": "test-secret",  # pragma: allowlist secret
        "WEB_SECURE_COOKIES": "false",
        "AUTH0_DOMAIN": "test.auth0.com",
        "AUTH0_CLIENT_ID": "cid",
        "AUTH0_CLIENT_SECRET": "csecret",  # pragma: allowlist secret
        "FEATURE_LIBRARY": "true",
        "FEATURE_DELETE": "true",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for key in ("ORCHESTRATOR_BASE_URL", "DATABASE_URL", "CONFIG_PATH"):
        monkeypatch.delenv(key, raising=False)

    from publisher_v2.config.source import get_config_source
    from publisher_v2.web.app import app, get_service
    from publisher_v2.web.auth import ADMIN_COOKIE_NAME, mint_admin_cookie_value
    from publisher_v2.web.routers import library

    get_config_source.cache_clear()
    get_service.cache_clear()
    library._delete_rate_limit.clear()
    s3 = _FakeS3()
    with patch("publisher_v2.services.managed_storage.boto3") as boto:
        boto.client = MagicMock(return_value=s3)
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-Requested-With": "XMLHttpRequest"},
            cookies={ADMIN_COOKIE_NAME: mint_admin_cookie_value(host="testserver")},
        )
        yield client, s3
    get_config_source.cache_clear()
    get_service.cache_clear()
    library._delete_rate_limit.clear()
    with contextlib.suppress(Exception):
        get_service()


@pytest.mark.parametrize(
    "filename",
    [
        "known.txt",  # a sidecar sitting next to a listed image
        "ghost.jpg",  # correct suffix, never in the listing
    ],
)
async def test_delete_non_image_suffix_or_unlisted_name_returns_404_and_nothing_deleted(
    delete_client_and_s3: tuple[httpx.AsyncClient, _FakeS3], filename: str
) -> None:
    client, s3 = delete_client_and_s3

    response = await client.delete(f"/api/library/objects/{filename}")

    assert response.status_code == 404, response.text
    assert s3.deleted == []


async def test_delete_listed_image_still_works(
    delete_client_and_s3: tuple[httpx.AsyncClient, _FakeS3],
) -> None:
    """Guard for the AC10 fix: the listed, correctly-suffixed name must still delete."""
    client, s3 = delete_client_and_s3

    response = await client.delete("/api/library/objects/known.jpg")

    assert response.status_code == 200, response.text
    assert f"{KEY_PREFIX}/known.jpg" in s3.deleted
