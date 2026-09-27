"""Shared harness for web layer tests (PUB-084 #298: every fake and builder defined once).

Everything here drives the real ``publisher_v2.web.app.app``, the real env-first config loader
and the real services. Fakes sit only at external client boundaries:

- ``FakeS3``       — the boto3 S3 client under the real ``ManagedStorage`` (``managed_real_app``)
- ``_FakeDropbox`` — the ``dropbox.Dropbox`` SDK client                   (``real_app_env``)
- ``FakeOpenAI``   — ``AsyncOpenAI``, the suite's one OpenAI fake (caption_pipeline_fakes.py)
- ``_FakeBot``     — ``telegram.Bot``                                      (``real_app_env``)
- ``_FakeSMTP``    — ``smtplib.SMTP``                                      (``real_app_env``)
"""

from __future__ import annotations

import email
import hashlib
import io
import json
from collections.abc import AsyncIterator, Callable, Generator, Iterable, Iterator, Mapping
from contextlib import ExitStack
from email.header import decode_header, make_header
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import dropbox
import httpx
import pytest
from botocore.exceptions import ClientError
from caption_pipeline_fakes import FakeOpenAI, install_fake_openai
from dropbox.exceptions import ApiError
from fastapi.testclient import TestClient
from PIL import Image

# ---------------------------------------------------------------------------------------------
# Shared caches the real app keeps between requests
# ---------------------------------------------------------------------------------------------


def _clear_app_caches() -> None:
    from publisher_v2.config.source import get_config_source
    from publisher_v2.web.dependencies import get_service
    from publisher_v2.web.routers import library

    get_config_source.cache_clear()
    get_service.cache_clear()
    library._upload_rate_limit.clear()
    library._delete_rate_limit.clear()


# ---------------------------------------------------------------------------------------------
# Admin clients
# ---------------------------------------------------------------------------------------------


@pytest.fixture
async def admin_asgi_client() -> AsyncIterator[Callable[..., httpx.AsyncClient]]:
    """Factory for httpx clients on the real app carrying a minted admin cookie (browser-shaped).

    Call it after the app's env is in place (``real_app_env``/``managed_real_app``).
    """
    from publisher_v2.web.app import app
    from publisher_v2.web.auth import ADMIN_COOKIE_NAME, mint_admin_cookie_value

    clients: list[httpx.AsyncClient] = []

    def _make(*, admin: bool = True) -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-Requested-With": "XMLHttpRequest"},
            cookies={ADMIN_COOKIE_NAME: mint_admin_cookie_value(host="testserver")} if admin else {},
        )
        clients.append(client)
        return client

    yield _make
    for client in clients:
        await client.aclose()


@pytest.fixture
def managed_admin_client(monkeypatch: pytest.MonkeyPatch, env_first_config: None) -> Generator[TestClient, None, None]:
    """TestClient configured for managed storage with admin."""
    monkeypatch.setenv("WEB_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    monkeypatch.setenv("AUTH0_CLIENT_ID", "cid")
    monkeypatch.setenv("AUTH0_CLIENT_SECRET", "cs")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
    monkeypatch.setenv("WEB_DEBUG", "true")
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)
    monkeypatch.setenv("CONFIG_SOURCE", "env")

    from publisher_v2.config.source import get_config_source

    get_config_source.cache_clear()

    from publisher_v2.web.app import app

    client = TestClient(app)
    yield client

    get_config_source.cache_clear()


# ---------------------------------------------------------------------------------------------
# Real app on Dropbox: fake SDK clients for Dropbox, OpenAI, Telegram and SMTP
# ---------------------------------------------------------------------------------------------

IMAGE_FOLDER = "/Photos"
FETLIFE_RECIPIENT = "fl@fetlife.example"
TELEGRAM_PUBLISHER = {"type": "telegram", "channel_id": "@chan"}
FETLIFE_PUBLISHER = {"type": "fetlife", "recipient": FETLIFE_RECIPIENT}


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 80, 60)).save(buf, format="JPEG")
    return buf.getvalue()


class _FakeDropbox:
    """In-memory stand-in for ``dropbox.Dropbox`` (the SDK client): one image in ``IMAGE_FOLDER``."""

    last: ClassVar[_FakeDropbox | None] = None

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.files: dict[str, bytes] = {f"{IMAGE_FOLDER}/img.jpg": _jpeg()}
        _FakeDropbox.last = self

    def _not_found(self) -> ApiError:
        err = dropbox.files.DownloadError.path(dropbox.files.LookupError.not_found)
        return ApiError("req", err, None, None)

    def files_list_folder(self, path: str) -> SimpleNamespace:
        entries = [
            dropbox.files.FileMetadata(
                name=p.rsplit("/", 1)[1], path_lower=p.lower(), content_hash=hashlib.sha256(p.encode()).hexdigest()
            )
            for p in self.files
            if p.rsplit("/", 1)[0] == path
        ]
        return SimpleNamespace(entries=entries, has_more=False, cursor=None)

    def files_download(self, path: str) -> tuple[None, SimpleNamespace]:
        if path not in self.files:
            raise self._not_found()
        return None, SimpleNamespace(content=self.files[path])

    def files_upload(self, data: bytes, path: str, **_kwargs: Any) -> None:
        self.files[path] = data

    def files_get_temporary_link(self, path: str) -> SimpleNamespace:
        return SimpleNamespace(link=f"https://dl.example/{path}")

    def files_get_metadata(self, path: str) -> dropbox.files.FileMetadata:
        return dropbox.files.FileMetadata(name=path.rsplit("/", 1)[1], id="id:1", rev="0123456789", size=1)

    def files_create_folder_v2(self, _path: str) -> None:
        return None

    def files_move_v2(self, src: str, dst: str, **_kwargs: Any) -> None:
        if src in self.files:
            self.files[dst] = self.files.pop(src)

    def files_delete_v2(self, path: str) -> None:
        self.files.pop(path, None)


VISION_REPLY: dict[str, Any] = {
    "description": "Rope on skin",
    "mood": "intimate",
    "tags": ["rope"],
    "nsfw": False,
    # PUB-051 AC5: sd_caption comes from the vision call, so the vision reply carries it.
    "sd_caption": "rope, skin",
}


def _openai_router(captions: Mapping[str, str], text_caption: str) -> Callable[[dict[str, Any]], Any]:
    """A ``FakeOpenAI`` script entry answering by request shape: vision, per-platform JSON, or text."""

    def _reply(kwargs: dict[str, Any]) -> Any:
        messages = kwargs.get("messages") or []
        user = messages[-1]["content"] if messages else ""
        if isinstance(user, list):  # vision call carries an image part
            return dict(VISION_REPLY)
        if (kwargs.get("response_format") or {}).get("type") == "json_object":
            # PUB-051 AC4: the caption call asks for platform keys only (no sd_caption), so route on
            # its shape — the one text-only json_object request — not on an "sd_caption" mention.
            return dict(captions)
        return text_caption

    return _reply


class _FakeBot:
    """``telegram.Bot`` stand-in recording each sent caption."""

    sent: ClassVar[list[str]] = []

    def __init__(self, token: str) -> None:
        self.token = token

    async def send_photo(self, chat_id: str, photo: Any, caption: str) -> SimpleNamespace:
        _FakeBot.sent.append(caption)
        return SimpleNamespace(message_id=1)

    async def shutdown(self) -> None:
        return None


class _FakeSMTP:
    """``smtplib.SMTP`` stand-in recording the (decoded) subject of every FetLife email."""

    subjects: ClassVar[list[str]] = []

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def starttls(self) -> None:
        return None

    def login(self, *_args: Any) -> None:
        return None

    def sendmail(self, _sender: str, rcpts: list[str], msg: str) -> None:
        if rcpts == [FETLIFE_RECIPIENT]:
            parsed = email.message_from_string(msg)
            _FakeSMTP.subjects.append(str(make_header(decode_header(parsed["Subject"]))))


class RealAppEnv:
    """What a ``real_app_env`` test can observe at the fake client boundaries."""

    openai: FakeOpenAI  # the installed OpenAI fake; ``.calls`` records every request

    @property
    def sent(self) -> list[str]:
        """Captions ``telegram.Bot.send_photo`` received, in order."""
        return _FakeBot.sent

    @property
    def subjects(self) -> list[str]:
        """Subjects of the emails sent to the FetLife recipient, in order."""
        return _FakeSMTP.subjects

    @property
    def dropbox_files(self) -> dict[str, bytes]:
        """The most recently built Dropbox client's files (path -> bytes)."""
        assert _FakeDropbox.last is not None, "no Dropbox client was built"
        return _FakeDropbox.last.files


@pytest.fixture
def real_app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[Callable[..., RealAppEnv]]:
    """Start the real app on env-first config with Dropbox storage and faked SDK clients.

    ``real_app_env(publishers=[...], captions={...}, text_caption="...", env={...})``:
    ``captions`` is the per-platform caption reply, ``text_caption`` the plain-text reply,
    ``env`` extra/overriding variables. No DATABASE_URL, so no publish store.
    """
    stack = ExitStack()

    def _start(
        *,
        publishers: Iterable[Mapping[str, Any]] = (TELEGRAM_PUBLISHER,),
        captions: Mapping[str, str] | None = None,
        text_caption: str = "",
        env: Mapping[str, str] | None = None,
    ) -> RealAppEnv:
        env_state = RealAppEnv()
        values = {
            "CONFIG_SOURCE": "env",
            "HOME": str(tmp_path),
            "STORAGE_PATHS": json.dumps({"root": IMAGE_FOLDER, "archive": "archive"}),
            "PUBLISHERS": json.dumps([dict(p) for p in publishers]),
            "EMAIL_SERVER": json.dumps({"sender": "bot@example.com", "smtp_server": "smtp.example", "smtp_port": 587}),
            "EMAIL_PASSWORD": "pw",  # pragma: allowlist secret
            "TELEGRAM_BOT_TOKEN": "tg",
            "OPENAI_SETTINGS": "{}",
            "OPENAI_API_KEY": "sk-test",
            "DROPBOX_APP_KEY": "k",
            "DROPBOX_APP_SECRET": "s",
            "DROPBOX_REFRESH_TOKEN": "r",
            "WEB_SESSION_SECRET": "test-secret",
            "WEB_SECURE_COOKIES": "false",
            "AUTH0_DOMAIN": "test.auth0.com",
            "AUTH0_CLIENT_ID": "cid",
            "AUTH0_CLIENT_SECRET": "csecret",  # pragma: allowlist secret
            "FEATURE_PUBLISH": "true",
            "FEATURE_ANALYZE_CAPTION": "true",
            **(env or {}),
        }
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        for key in ("ORCHESTRATOR_BASE_URL", "DATABASE_URL", "CONFIG_PATH", "INSTA_PASSWORD"):
            monkeypatch.delenv(key, raising=False)
        env_state.openai = install_fake_openai(
            monkeypatch, FakeOpenAI(script=[_openai_router(captions or {}, text_caption)])
        )
        _FakeBot.sent = []
        _FakeSMTP.subjects = []
        _FakeDropbox.last = None
        _clear_app_caches()
        stack.enter_context(patch("publisher_v2.services.storage.dropbox.Dropbox", _FakeDropbox))
        stack.enter_context(patch("publisher_v2.services.publishers.telegram.telegram.Bot", _FakeBot))
        stack.enter_context(patch("publisher_v2.services.publishers.email.smtplib.SMTP", _FakeSMTP))
        return env_state

    yield _start
    stack.close()
    _clear_app_caches()


# ---------------------------------------------------------------------------------------------
# Real app on managed storage: the boto3 S3 client faked per key
# ---------------------------------------------------------------------------------------------

MANAGED_ROOT = "/tenant/instance"
MANAGED_KEY_PREFIX = MANAGED_ROOT.strip("/")
R2_ENDPOINT = "https://accountid.r2.cloudflarestorage.com"

MANAGED_ENV: dict[str, str] = {
    "CONFIG_SOURCE": "env",
    "STORAGE_PROVIDER": "managed",
    "R2_ACCESS_KEY_ID": "ak",
    "R2_SECRET_ACCESS_KEY": "sk",  # pragma: allowlist secret
    "R2_ENDPOINT_URL": R2_ENDPOINT,
    "R2_BUCKET_NAME": "bucket",
    "STORAGE_PATHS": json.dumps({"root": MANAGED_ROOT, "archive": "archive", "keep": "keep", "remove": "reject"}),
    "PUBLISHERS": json.dumps([TELEGRAM_PUBLISHER]),
    "TELEGRAM_BOT_TOKEN": "tg",
    "OPENAI_SETTINGS": "{}",
    "OPENAI_API_KEY": "sk-test",  # pragma: allowlist secret
    "WEB_SESSION_SECRET": "test-secret",  # pragma: allowlist secret
    "WEB_SECURE_COOKIES": "false",
    "AUTH0_DOMAIN": "test.auth0.com",
    "AUTH0_CLIENT_ID": "cid",
    "AUTH0_CLIENT_SECRET": "csecret",  # pragma: allowlist secret
    "FEATURE_LIBRARY": "true",
}


def _s3_error(code: str, operation: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "Not Found"}}, operation)


class FakeS3:
    """The boto3 S3 client, in memory, answering per key.

    ``head_object``/``get_object`` answer from the objects this fake holds (seeded with
    ``add``, written with ``put_object``/``copy_object``, removed with ``delete_object``);
    anything else is a 404 (PUB-048 AC9/AC11). Listings honour ``Prefix`` and ``Delimiter``
    as S3 does. ``puts``, ``copied`` and ``deleted`` record what the app asked for.
    """

    # Above this, a body is kept by size only: keeping a copy would add to the
    # peak-memory assertions (#136). Every test that inspects bytes uploads far less.
    _KEEP_BODY_UNDER = 256 * 1024

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, int]] = {}
        self.puts: list[dict[str, Any]] = []
        self.copied: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    # -- seeding and inspection --

    def add(self, key: str, body: bytes = b"0123456789") -> None:
        """Place an object as if another writer had put it (not recorded in ``puts``)."""
        self.objects[key] = (body, len(body))

    def body(self, index: int = 0) -> bytes:
        """The bytes of put number ``index`` (empty for a body kept by size only)."""
        return bytes(self.puts[index]["Body"])

    # -- boto3 client surface --

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        # Consume a file-like Body inside the call, the way botocore does: the caller
        # is entitled to close it on return, and a fake that read it afterwards would
        # fail against correct code.
        body = kwargs["Body"]
        if hasattr(body, "read"):
            body.seek(0)
            # 64 KiB at a time, keeping the copy only while it stays under the threshold:
            # reading a big head up front would put the harness's own allocation into the
            # peak-memory assertions.
            kept: bytearray | None = bytearray()
            size = 0
            while chunk := body.read(64 * 1024):
                size += len(chunk)
                if kept is not None:
                    if size <= self._KEEP_BODY_UNDER:
                        kept.extend(chunk)
                    else:
                        kept = None
            data = bytes(kept) if kept is not None else b""
        else:
            data = bytes(body)
            size = len(data)
            if size > self._KEEP_BODY_UNDER:
                data = b""
        self.puts.append({**kwargs, "Body": data, "Size": size})
        self.objects[kwargs["Key"]] = (data, size)
        return {}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        key = kwargs["Key"]
        if key not in self.objects:
            raise _s3_error("404", "HeadObject")
        return {"ContentLength": self.objects[key][1], "ETag": '"e"', "LastModified": None}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        key = kwargs["Key"]
        if key not in self.objects:
            raise _s3_error("NoSuchKey", "GetObject")
        data, size = self.objects[key]
        return {"Body": io.BytesIO(data), "ContentLength": len(data), "ETag": '"e"', "Size": size}

    def copy_object(self, **kwargs: Any) -> dict[str, Any]:
        src = kwargs["CopySource"]["Key"]
        if src not in self.objects:
            raise _s3_error("NoSuchKey", "CopyObject")
        self.copied.append((src, kwargs["Key"]))
        self.objects[kwargs["Key"]] = self.objects[src]
        return {}

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self.deleted.append(kwargs["Key"])
        self.objects.pop(kwargs["Key"], None)
        return {}

    def _page(self, prefix: str, delimiter: str | None) -> dict[str, Any]:
        contents: list[dict[str, Any]] = []
        common: set[str] = set()
        for key in sorted(self.objects):
            if not key.startswith(prefix):
                continue
            rest = key[len(prefix) :]
            if delimiter and delimiter in rest:
                common.add(prefix + rest.split(delimiter, 1)[0] + delimiter)
                continue
            contents.append({"Key": key, "Size": self.objects[key][1], "LastModified": None, "ETag": '"e"'})
        return {
            "Contents": contents,
            "CommonPrefixes": [{"Prefix": p} for p in sorted(common)],
            "IsTruncated": False,
        }

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        return self._page(kwargs.get("Prefix", ""), kwargs.get("Delimiter"))

    def get_paginator(self, _name: str) -> Any:
        fake = self

        class _Paginator:
            def paginate(self, **kwargs: Any) -> list[dict[str, Any]]:
                return [fake._page(kwargs.get("Prefix", ""), kwargs.get("Delimiter"))]

        return _Paginator()

    def generate_presigned_url(self, _method: str, Params: dict[str, Any], **_kwargs: Any) -> str:  # noqa: N803
        return f"{R2_ENDPOINT}/{Params['Bucket']}/{Params['Key']}?X-Amz-Signature=fake"

    def close(self) -> None:
        return None


@pytest.fixture
def fake_s3() -> FakeS3:
    """A bare per-key S3 fake (for tests of the fake itself)."""
    return FakeS3()


@pytest.fixture
def managed_real_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[Callable[..., FakeS3]]:
    """Start the real app on env-first managed storage; boto3's S3 client is a ``FakeS3``.

    ``managed_real_app(env={...}, objects=[...])``: ``env`` overrides ``MANAGED_ENV`` (a
    ``None`` value unsets the variable); ``objects`` are keys the bucket already holds.
    Returns the fake, so the test can seed and inspect it.
    """
    started = False

    def _start(*, env: Mapping[str, str | None] | None = None, objects: Iterable[str] = ()) -> FakeS3:
        nonlocal started
        started = True
        for key, value in {**MANAGED_ENV, "HOME": str(tmp_path), **(env or {})}.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        for key in ("ORCHESTRATOR_BASE_URL", "DATABASE_URL", "CONFIG_PATH"):
            monkeypatch.delenv(key, raising=False)
        fake = FakeS3()
        for key in objects:
            fake.add(key)
        monkeypatch.setattr("publisher_v2.services.managed_storage.boto3.client", lambda *a, **k: fake)
        _clear_app_caches()
        return fake

    yield _start
    if started:
        _clear_app_caches()


# ---------------------------------------------------------------------------------------------
# #136: streamed library uploads through the real app
# ---------------------------------------------------------------------------------------------

UPLOAD_BOUNDARY = "pv2boundary"
UPLOAD_CHUNK = 64 * 1024


class CountingUploadBody:
    """Multipart body streamed in UPLOAD_CHUNK pieces; records how many bytes the app pulled."""

    def __init__(self, payload: bytes, filename: str = "img.png", pad_to: int = 0) -> None:
        head = (
            f'--{UPLOAD_BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode()
        tail = f"\r\n--{UPLOAD_BOUNDARY}--\r\n".encode()
        self.data = head + payload + (b"\0" * max(0, pad_to - len(payload))) + tail
        self.pulled = 0

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        for i in range(0, len(self.data), UPLOAD_CHUNK):
            piece = self.data[i : i + UPLOAD_CHUNK]
            self.pulled += len(piece)
            yield piece


class _UploadHarness:
    def __init__(self, s3: FakeS3) -> None:
        self.s3 = s3

    @staticmethod
    def png(width: int, height: int, noise: bool = False, mode: str = "RGB") -> bytes:
        import os

        buf = io.BytesIO()
        if noise:
            img = Image.frombytes("RGB", (width, height), os.urandom(width * height * 3))
        else:
            img = Image.new(mode, (width, height), 200 if mode == "L" else (200, 100, 50))
        img.save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def body(payload: bytes, filename: str = "img.png", pad_to: int = 0) -> CountingUploadBody:
        return CountingUploadBody(payload, filename=filename, pad_to=pad_to)

    async def post(  # type: ignore[no-untyped-def]
        self,
        body,
        *,
        admin: bool = True,
        cookie: str | None = None,
        headers: dict[str, str] | None = None,
        query: str = "",
    ):
        from publisher_v2.web.app import app
        from publisher_v2.web.auth import ADMIN_COOKIE_NAME, mint_admin_cookie_value

        if cookie is None and admin:
            cookie = mint_admin_cookie_value(host="testserver")
        cookies = {ADMIN_COOKIE_NAME: cookie} if cookie else {"other": "1"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver", cookies=cookies
        ) as client:
            return await client.post(
                f"/api/library/upload{query}",
                content=body,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={UPLOAD_BOUNDARY}",
                    "X-Requested-With": "XMLHttpRequest",
                    **(headers or {}),
                },
            )


@pytest.fixture
def library_upload(managed_real_app: Callable[..., FakeS3]) -> _UploadHarness:
    """Real app + env-first managed storage with a 2 MB upload cap; boto3 client faked."""
    return _UploadHarness(managed_real_app(env={"LIBRARY_MAX_UPLOAD_MB": "2"}))


# ---------------------------------------------------------------------------------------------
# Library router tests on a stubbed service (PUB-031/PUB-032)
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def _clear_rate_limit() -> Iterator[None]:
    """Clear the library upload/delete rate limits around a test."""
    from publisher_v2.web.routers.library import _delete_rate_limit, _upload_rate_limit

    _upload_rate_limit.clear()
    _delete_rate_limit.clear()
    yield
    _upload_rate_limit.clear()
    _delete_rate_limit.clear()


@pytest.fixture
def library_service() -> MagicMock:
    """A stand-in ``WebImageService`` with managed storage configured and the library on."""
    svc = MagicMock()
    svc.config.managed = MagicMock()  # Not None -> library available
    svc.config.features.library_enabled = True
    svc.config.storage_paths.image_folder = "tenant/instance"
    svc.config.storage_paths.archive_folder = "archive"
    svc.config.storage_paths.folder_keep = "keep"
    svc.config.storage_paths.folder_remove = "reject"
    svc.storage = MagicMock()
    # #144: the move endpoint verifies the name against the listing.
    svc.ensure_known_image = AsyncMock(return_value=None)
    return svc


@pytest.fixture
def managed_app(
    monkeypatch: pytest.MonkeyPatch, library_service: MagicMock, _clear_rate_limit: None
) -> Generator[TestClient, None, None]:
    """TestClient with ``library_service`` as the request service and header + admin auth configured."""
    monkeypatch.setenv("WEB_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    monkeypatch.setenv("AUTH0_CLIENT_ID", "cid")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("WEB_SECURE_COOKIES", "false")
    monkeypatch.setenv("WEB_DEBUG", "true")
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)
    monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

    from publisher_v2.web.app import app
    from publisher_v2.web.dependencies import get_request_service

    app.dependency_overrides[get_request_service] = lambda: library_service

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()


@pytest.fixture
def admin_headers() -> dict[str, str]:
    """Header auth matching ``managed_app``'s WEB_AUTH_TOKEN."""
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def admin_cookies() -> dict[str, str]:
    """A signed admin cookie for the test client's host."""
    from publisher_v2.web.auth import ADMIN_COOKIE_NAME, mint_admin_cookie_value

    return {ADMIN_COOKIE_NAME: mint_admin_cookie_value(host="testserver")}


# ---------------------------------------------------------------------------------------------
# WebImageService for the analyze path, with stubbed storage and AI calls
# ---------------------------------------------------------------------------------------------

_DEFAULT_CAPTION_RESULT: tuple[Any, ...] = ({"generic": "fresh AI caption"}, "fresh sd", [], {})  # PUB-051: + angles


@pytest.fixture
def analyze_service(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Any]:
    """Build a real ``WebImageService`` (env-first, Dropbox SDK patched) for ``analyze_and_caption`` tests.

    ``analyze_service(sidecar=..., env={...}, caption_result=(...), image_bytes=...)``. The
    listing holds ``img.jpg``; vision returns a fixed analysis; the multi-caption call returns
    ``caption_result``; the caption-only fallback fails the test if it ever runs (it would
    otherwise reach api.openai.com with the test key).
    """

    def _build(
        *,
        sidecar: str | None = None,
        env: Mapping[str, str] | None = None,
        caption_result: tuple[Any, ...] = _DEFAULT_CAPTION_RESULT,
        image_bytes: bytes = b"image-bytes",
        listing: Iterable[str] = ("img.jpg",),
    ) -> Any:
        from publisher_v2.core.models import ImageAnalysis

        values = {
            "STORAGE_PATHS": '{"root": "/Photos", "archive": "archive"}',
            "PUBLISHERS": "[]",
            "OPENAI_SETTINGS": "{}",
            "OPENAI_API_KEY": "sk-test",
            "DROPBOX_APP_KEY": "test_key",
            "DROPBOX_APP_SECRET": "test_secret",  # pragma: allowlist secret
            "DROPBOX_REFRESH_TOKEN": "test_refresh",
            **(env or {}),
        }
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)

        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.web.service import WebImageService

            service = WebImageService()

        service.storage.get_temporary_link = AsyncMock(return_value="http://temp")
        # #91 (SEC-11): analyze validates the filename against the image listing.
        service.storage.list_images = AsyncMock(return_value=list(listing))
        # #93: vision consumes the downloaded bytes instead of the presigned link.
        service.storage.download_image = AsyncMock(return_value=image_bytes)
        blob = sidecar.encode() if sidecar is not None else None
        service.storage.download_sidecar_if_exists = AsyncMock(return_value=blob)

        analysis = ImageAnalysis(description="Test", mood="neutral", tags=["t"], nsfw=False, safety_labels=[])
        service.ai_service.analyzer.analyze = AsyncMock(return_value=(analysis, None))
        service.ai_service.create_multi_caption_pair_from_analysis = AsyncMock(return_value=caption_result)
        service.ai_service.create_caption_from_analysis = AsyncMock(
            side_effect=AssertionError("caption-only fallback ran; the multi-caption path failed")
        )
        return service

    return _build
