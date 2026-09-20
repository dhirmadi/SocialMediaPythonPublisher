"""#147: the web UI must show, edit and publish each platform's own caption.

Everything runs through the real ``publisher_v2.web.app.app`` over
``httpx.ASGITransport`` with the real env-first config loader, the real
``WebImageService``, ``AIService`` (caption parsing), ``WorkflowOrchestrator``
and publishers. Fakes sit only at the external client boundaries: the Dropbox
SDK client, the OpenAI client, ``telegram.Bot`` and ``smtplib.SMTP``.
"""

from __future__ import annotations

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

from publisher_v2.utils.captions import format_caption

IMAGE_FOLDER = "/Photos"
TELEGRAM_CAPTION = ("Rope marks on warm skin, a long slow evening told in knots and patience. " * 10).strip()
EMAIL_CAPTION = "Rope marks on warm skin; a slow evening in knots."


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 80, 60)).save(buf, format="JPEG")
    return buf.getvalue()


class _FakeDropbox:
    """In-memory stand-in for ``dropbox.Dropbox`` (the SDK client)."""

    last: _FakeDropbox | None = None

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


async def test_analyze_returns_every_platform_caption_and_email_first_caption(client: httpx.AsyncClient) -> None:
    res = await client.post("/api/images/img.jpg/analyze")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["platform_captions"] == {"telegram": TELEGRAM_CAPTION, "email": EMAIL_CAPTION}
    assert body["caption"] == EMAIL_CAPTION
    assert len(body["caption"]) <= 240
    assert body["platform_limits"] == {"telegram": 4096, "email": 240}


async def test_publish_with_per_platform_captions_sends_each_its_own(client: httpx.AsyncClient) -> None:
    tg = "Telegram gets the long one, knots and patience and the whole evening."
    em = "FetLife gets its own short line."
    res = await client.post("/api/images/img.jpg/publish", json={"captions": {"telegram": tg, "email": em}})
    assert res.status_code == 200, res.text
    assert res.json()["any_success"] is True, res.json()
    assert _FakeBot.sent == [format_caption("telegram", tg)]
    assert _FakeSMTP.subjects == [format_caption("email", em)]


async def test_publish_email_never_gets_truncated_telegram_text(client: httpx.AsyncClient) -> None:
    """Operator-edited texts (not the AI's): a 700-char Telegram caption must not leak, trimmed, into email."""
    long_tg = ("The operator rewrote the long Telegram story by hand, slower and warmer this time. " * 9).strip()
    short_em = "Operator's own FetLife line."
    assert len(long_tg) > 700
    res = await client.post("/api/images/img.jpg/publish", json={"captions": {"telegram": long_tg, "email": short_em}})
    assert res.status_code == 200, res.text
    assert _FakeSMTP.subjects == [short_em]
    assert _FakeBot.sent == [format_caption("telegram", long_tg)]


async def test_legacy_single_caption_still_reaches_all_platforms(client: httpx.AsyncClient) -> None:
    legacy = "One caption for every platform."
    res = await client.post("/api/images/img.jpg/publish", json={"caption": legacy})
    assert res.status_code == 200, res.text
    assert _FakeBot.sent == [format_caption("telegram", legacy)]
    assert _FakeSMTP.subjects == [format_caption("email", legacy)]


async def test_cached_analyze_returns_full_generated_dict(client: httpx.AsyncClient) -> None:
    """Second analyze hits the sidecar cache: all generated captions, caption is the email one."""
    first = await client.post("/api/images/img.jpg/analyze")
    assert first.status_code == 200, first.text
    second = await client.post("/api/images/img.jpg/analyze")
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["cached"] is True
    assert body["platform_captions"] == {"telegram": TELEGRAM_CAPTION, "email": EMAIL_CAPTION}
    assert body["caption"] == EMAIL_CAPTION
    assert body["platform_limits"] == {"telegram": 4096, "email": 240}


async def test_image_details_surface_generated_captions(client: httpx.AsyncClient) -> None:
    await client.post("/api/images/img.jpg/analyze")
    res = await client.get("/api/images/img.jpg")
    assert res.status_code == 200, res.text
    assert res.json()["caption_generated"] == {"telegram": TELEGRAM_CAPTION, "email": EMAIL_CAPTION}


async def test_image_details_carry_platform_limits(client: httpx.AsyncClient) -> None:
    res = await client.get("/api/images/img.jpg")
    assert res.status_code == 200, res.text
    assert res.json()["platform_limits"] == {"telegram": 4096, "email": 240}


async def test_served_ui_has_per_platform_editors_and_no_fixed_240(client: httpx.AsyncClient) -> None:
    html = (await client.get("/")).text
    assert 'id="caption-editors"' in html
    assert 'id="caption-text"' not in html  # the single shared editor is gone
    assert "const maxLen = 240" not in html
    assert "const maxLen = platformLimits[platform];" in html
    # Publish sends the per-platform dict, not one caption for everyone.
    assert "JSON.stringify(isPlaceholder ? { caption: null } : { captions })" in html
    # A partly filled set is stopped in the UI too (the server answers 400).
    assert "missingCaptionPlatforms(captions)" in html


async def test_partial_captions_rejected_so_email_never_borrows_telegram_text(client: httpx.AsyncClient) -> None:
    """A dict missing an enabled platform must not fall back to another platform's (trimmed) text."""
    long_tg = ("Only the Telegram story was written, long and slow, knot after knot. " * 11).strip()
    res = await client.post("/api/images/img.jpg/publish", json={"captions": {"telegram": long_tg}})
    assert res.status_code == 400, res.text
    assert "email" in res.text
    assert _FakeBot.sent == []
    assert _FakeSMTP.subjects == []


async def test_unknown_platform_in_captions_rejected(client: httpx.AsyncClient) -> None:
    res = await client.post(
        "/api/images/img.jpg/publish",
        json={"captions": {"telegram": "a", "email": "b", "myspace": "c"}},
    )
    assert res.status_code == 400, res.text
    assert _FakeBot.sent == [] and _FakeSMTP.subjects == []


@pytest.fixture
def no_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the image in place after publishing, as an operator retrying a platform would."""
    monkeypatch.setenv("CONTENT_SETTINGS", json.dumps({"hashtag_string": "", "archive": False, "debug": False}))


async def test_edited_captions_survive_the_publish_and_come_back(no_archive: None, client: httpx.AsyncClient) -> None:
    """#147: the operator's edits must be what the UI shows afterwards.

    Collapsing the override dict to one string meant the sidecar kept the AI's
    text, so every editor refilled with the pre-edit caption and the operator's
    Telegram edit was shown nowhere — and on a retry of a failed platform, the
    replaced text would have been published again.
    """
    await client.post("/api/images/img.jpg/analyze")
    tg = "OPERATOR EDITED the telegram line, knots and patience."
    em = "OPERATOR EDITED the email line."

    published = await client.post("/api/images/img.jpg/publish", json={"captions": {"telegram": tg, "email": em}})
    assert published.status_code == 200, published.text

    sidecar = (_FakeDropbox.last.files[f"{IMAGE_FOLDER}/img.txt"]).decode()
    assert "caption_published" in sidecar, sidecar
    assert tg in sidecar and em in sidecar

    details = await client.get("/api/images/img.jpg")
    assert details.status_code == 200, details.text
    assert details.json()["caption_generated"] == {"telegram": tg, "email": em}

    cached = await client.post("/api/images/img.jpg/analyze")
    assert cached.status_code == 200, cached.text
    assert cached.json()["platform_captions"] == {"telegram": tg, "email": em}
    assert cached.json()["caption"] == em, "the email editor must not refill with the AI text"


async def test_the_service_rejects_a_partial_dict_even_without_the_route(no_archive: None, real_app: None) -> None:
    """#147: the route's guard is an early exit, not the only one.

    ``publish_image`` is reachable from scripts and future callers; a partial
    dict one level below the route used to let email receive 240 characters of
    the Telegram text — the exact bug this issue exists to close.
    """
    from publisher_v2.core.exceptions import CaptionCoverageError
    from publisher_v2.web.app import get_service

    service = get_service()

    with pytest.raises(CaptionCoverageError, match="missing="):
        await service.publish_image("img.jpg", None, caption_overrides={"telegram": "T" * 700})

    assert _FakeSMTP.subjects == [], "email received something from a rejected publish"
    assert _FakeBot.sent == []
