"""#139: without a publish store, two concurrent publishes must not double-post.

Everything runs through the real ``publisher_v2.web.app.app`` over
``httpx.ASGITransport``, the real env-first config loader, ``WebImageService``,
``WorkflowOrchestrator`` and publishers, with DATABASE_URL unset so no publish
store exists. Fakes sit only at the external client boundaries (Dropbox SDK,
OpenAI, ``telegram.Bot``, ``smtplib.SMTP``).
"""

from __future__ import annotations

import asyncio
import email
import hashlib
import io
import json
from collections.abc import AsyncIterator, Iterator
from email.header import decode_header, make_header
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import dropbox
import httpx
import pytest
from dropbox.exceptions import ApiError
from PIL import Image

IMAGE_FOLDER = "/Photos"
TELEGRAM_CAPTION = ("Rope marks on warm skin, a long slow evening told in knots and patience. " * 10).strip()
EMAIL_CAPTION = "Rope marks on warm skin; a slow evening in knots."


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 80, 60)).save(buf, format="JPEG")
    return buf.getvalue()


class _FakeDropbox:
    """In-memory stand-in for ``dropbox.Dropbox`` (the SDK client)."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.files: dict[str, bytes] = {f"{IMAGE_FOLDER}/img.jpg": _jpeg()}

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


class _FakeCompletions:
    def __init__(self, owner: _FakeOpenAI) -> None:
        self._owner = owner

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        messages = kwargs.get("messages") or []
        user = messages[-1]["content"] if messages else ""
        if isinstance(user, list):  # vision call carries an image part
            content = json.dumps({"description": "Rope on skin", "mood": "intimate", "tags": ["rope"], "nsfw": False})
        elif "sd_caption" in str(user):
            content = json.dumps(self._owner.multi_payload)
        else:
            content = EMAIL_CAPTION
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=None,
        )


class _FakeOpenAI:
    multi_payload: dict[str, str] = {}

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(self))

    async def close(self) -> None:
        return None


class _FakeBot:
    sent: list[str] = []

    def __init__(self, token: str) -> None:
        self.token = token

    async def send_photo(self, chat_id: str, photo: Any, caption: str) -> SimpleNamespace:
        _FakeBot.sent.append(caption)
        return SimpleNamespace(message_id=1)

    async def shutdown(self) -> None:
        return None


class _FakeSMTP:
    subjects: list[str] = []

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
        if rcpts == ["fl@fetlife.example"]:
            parsed = email.message_from_string(msg)
            _FakeSMTP.subjects.append(str(make_header(decode_header(parsed["Subject"]))))


@pytest.fixture
def real_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[None]:
    env = {
        "CONFIG_SOURCE": "env",
        "HOME": str(tmp_path),
        "STORAGE_PATHS": json.dumps({"root": IMAGE_FOLDER, "archive": "archive"}),
        "PUBLISHERS": json.dumps(
            [
                {"type": "telegram", "channel_id": "@chan"},
                {"type": "fetlife", "recipient": "fl@fetlife.example"},
            ]
        ),
        "EMAIL_SERVER": json.dumps({"sender": "bot@example.com", "smtp_server": "smtp.example", "smtp_port": 587}),
        "EMAIL_PASSWORD": "pw",
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
        "AUTH0_CLIENT_SECRET": "csecret",
        "FEATURE_PUBLISH": "true",
        "FEATURE_ANALYZE_CAPTION": "true",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for key in ("ORCHESTRATOR_BASE_URL", "DATABASE_URL", "CONFIG_PATH", "INSTA_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    _FakeOpenAI.multi_payload = {"telegram": TELEGRAM_CAPTION, "email": EMAIL_CAPTION, "sd_caption": "rope, skin"}
    _FakeBot.sent = []
    _FakeSMTP.subjects = []

    from publisher_v2.config.source import get_config_source
    from publisher_v2.web.app import get_service

    get_config_source.cache_clear()
    get_service.cache_clear()
    with (
        patch("publisher_v2.services.storage.dropbox.Dropbox", _FakeDropbox),
        patch("publisher_v2.services.ai.AsyncOpenAI", _FakeOpenAI),
        patch("publisher_v2.services.publishers.telegram.telegram.Bot", _FakeBot),
        patch("publisher_v2.services.publishers.email.smtplib.SMTP", _FakeSMTP),
    ):
        yield
    get_config_source.cache_clear()
    get_service.cache_clear()


@pytest.fixture
async def client(real_app: None) -> AsyncIterator[httpx.AsyncClient]:
    from publisher_v2.web.app import app
    from publisher_v2.web.auth import ADMIN_COOKIE_NAME, mint_admin_cookie_value

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-Requested-With": "XMLHttpRequest"},
        cookies={ADMIN_COOKIE_NAME: mint_admin_cookie_value(host="testserver")},
    ) as c:
        yield c


async def test_two_concurrent_publishes_post_once_per_platform(client: httpx.AsyncClient) -> None:
    """The web double-click with no DB behind it: each platform sees exactly one post."""
    first, second = await asyncio.gather(
        client.post("/api/images/img.jpg/publish", json={"caption": "One line."}),
        client.post("/api/images/img.jpg/publish", json={"caption": "One line."}),
    )

    assert sorted([first.status_code, second.status_code]) == [200, 409], (first.text, second.text)
    blocked = first if first.status_code == 409 else second
    assert blocked.json()["detail"] == "Publish already in progress", blocked.text
    assert len(_FakeBot.sent) == 1, _FakeBot.sent
    assert len(_FakeSMTP.subjects) == 1, _FakeSMTP.subjects


async def test_sequential_second_publish_is_refused_with_409(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Archiving off: the image stays selectable, so only the posted-state check can block it."""
    monkeypatch.setenv("CONTENT_SETTINGS", json.dumps({"hashtag_string": "", "archive": False}))

    from publisher_v2.web.app import get_service

    get_service.cache_clear()
    first = await client.post("/api/images/img.jpg/publish", json={"caption": "One line."})
    assert first.status_code == 200, first.text
    second = await client.post("/api/images/img.jpg/publish", json={"caption": "One line."})

    assert second.status_code == 409, second.text
    assert second.json()["detail"] == "Image already published", second.text

    assert len(_FakeBot.sent) == 1, _FakeBot.sent
    assert len(_FakeSMTP.subjects) == 1, _FakeSMTP.subjects


class TestThePublishLockMapIsBounded:
    """#139 NIT: one lock per (tenant, image) ever published, kept for the life of the process."""

    async def test_idle_locks_are_dropped_but_a_held_one_survives(self) -> None:
        import asyncio

        from publisher_v2.web import service as service_module

        loop = asyncio.get_running_loop()
        service_module._PUBLISH_LOCKS.pop(loop, None)

        held = service_module._publish_lock("t1", "held.jpg")
        await held.acquire()
        try:
            for i in range(service_module._PUBLISH_LOCK_MAX_KEYS + 50):
                service_module._publish_lock("t1", f"idle-{i}.jpg")

            per_loop = service_module._PUBLISH_LOCKS[loop]
            assert len(per_loop) <= service_module._PUBLISH_LOCK_MAX_KEYS
            # Evicting a held lock would let the next click build a fresh one and
            # lose the serialization the lock exists for.
            assert service_module._publish_lock("t1", "held.jpg") is held
        finally:
            held.release()
            service_module._PUBLISH_LOCKS.pop(loop, None)
