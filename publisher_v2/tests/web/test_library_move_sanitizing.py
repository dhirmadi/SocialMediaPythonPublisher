"""#144 item 5: the move endpoint passed the raw path parameter to storage.

delete_object sanitizes its filename; move_object did not, so a traversal-ish
name was interpolated straight into the source and destination keys, and any
name at all was accepted whether or not it was in the listing.

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
    """Records copy/delete calls; lists exactly one object in the image folder."""

    def __init__(self) -> None:
        self.copied: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def get_paginator(self, _name: str) -> Any:
        keys = [f"{KEY_PREFIX}/known.jpg"]

        class _Paginator:
            def paginate(self, **_kwargs: Any) -> Any:
                return [{"Contents": [{"Key": k, "Size": 10, "LastModified": None} for k in keys]}]

        return _Paginator()

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        return {"ETag": '"e"', "ContentLength": 10, "LastModified": None}

    def copy_object(self, **kwargs: Any) -> dict[str, Any]:
        self.copied.append((kwargs["CopySource"]["Key"], kwargs["Key"]))
        return {}

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self.deleted.append(kwargs["Key"])
        return {}

    def close(self) -> None:
        return None


@pytest.fixture
def client_and_s3(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[tuple[httpx.AsyncClient, _FakeS3]]:
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
        "OPENAI_API_KEY": "sk-test",
        "WEB_SESSION_SECRET": "test-secret",
        "WEB_SECURE_COOKIES": "false",
        "AUTH0_DOMAIN": "test.auth0.com",
        "AUTH0_CLIENT_ID": "cid",
        "AUTH0_CLIENT_SECRET": "csecret",
        "FEATURE_LIBRARY": "true",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for key in ("ORCHESTRATOR_BASE_URL", "DATABASE_URL", "CONFIG_PATH"):
        monkeypatch.delenv(key, raising=False)

    from publisher_v2.config.source import get_config_source
    from publisher_v2.web.app import app, get_service
    from publisher_v2.web.auth import ADMIN_COOKIE_NAME, mint_admin_cookie_value

    get_config_source.cache_clear()
    get_service.cache_clear()
    s3 = _FakeS3()
    with patch("publisher_v2.services.managed_storage.boto3") as boto:
        boto.client = MagicMock(return_value=s3)
        transport = httpx.ASGITransport(app=app)
        client = httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"X-Requested-With": "XMLHttpRequest"},
            cookies={ADMIN_COOKIE_NAME: mint_admin_cookie_value(host="testserver")},
        )
        yield client, s3
    get_config_source.cache_clear()
    get_service.cache_clear()
    with contextlib.suppress(Exception):
        get_service()


async def _move(client: httpx.AsyncClient, filename: str) -> httpx.Response:
    return await client.post(f"/api/library/objects/{filename}/move", json={"target_folder": "archive"})


async def test_traversal_name_never_reaches_storage(client_and_s3: tuple[httpx.AsyncClient, _FakeS3]) -> None:
    client, s3 = client_and_s3

    response = await _move(client, "..%2Fx.jpg")

    assert response.status_code in (400, 404), response.text
    assert s3.copied == []
    assert s3.deleted == []


async def test_unlisted_name_is_404(client_and_s3: tuple[httpx.AsyncClient, _FakeS3]) -> None:
    client, s3 = client_and_s3

    response = await _move(client, "not-in-the-listing.jpg")

    assert response.status_code == 404, response.text
    assert s3.copied == []


async def test_listed_name_still_moves(client_and_s3: tuple[httpx.AsyncClient, _FakeS3]) -> None:
    client, s3 = client_and_s3

    response = await _move(client, "known.jpg")

    assert response.status_code == 200, response.text
    assert (f"{KEY_PREFIX}/known.jpg", f"{KEY_PREFIX}/archive/known.jpg") in s3.copied
