from __future__ import annotations

import email
from email.header import decode_header
from pathlib import Path
from types import SimpleNamespace

import pytest
from instagrapi.exceptions import (
    BadCredentials,
    BadPassword,
    CaptchaChallengeRequired,
    ChallengeRequired,
    ChallengeUnknownStep,
    ClientConnectionError,
    ClientThrottledError,
    FeedbackRequired,
    LoginRequired,
    PhotoNotUpload,
    PleaseWaitFewMinutes,
    ProxyAddressIsBlocked,
    RateLimitError,
    SentryBlock,
    TwoFactorRequired,
)
from PIL import Image

from publisher_v2.config.schema import EmailConfig, InstagramConfig, TelegramConfig
from publisher_v2.services.publishers.email import EmailPublisher
from publisher_v2.services.publishers.instagram import InstagramPublisher
from publisher_v2.services.publishers.telegram import TelegramPublisher


class _DummySMTP:
    def __init__(self, *_args, **_kwargs) -> None:
        self.starttls_called = False
        self.login_args: tuple[str, str] | None = None
        self.sent_messages: list[tuple[str, tuple[str, ...], str]] = []
        self.closed = False
        self.fail = False

    # Context-manager protocol — the publisher now uses ``with smtplib.SMTP(...)``
    # so QUIT/close always runs even when sendmail raises.
    def __enter__(self) -> _DummySMTP:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.quit()

    def starttls(self) -> None:
        if self.fail:
            raise RuntimeError("tls failure")
        self.starttls_called = True

    def login(self, user: str, pwd: str) -> None:
        if self.fail:
            raise RuntimeError("login failure")
        self.login_args = (user, pwd)

    def sendmail(self, sender: str, recipients: list[str], message: str) -> None:
        if self.fail:
            raise RuntimeError("send failure")
        self.sent_messages.append((sender, tuple(recipients), message))

    def quit(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_email_publisher_disabled_without_config() -> None:
    publisher = EmailPublisher(config=None, enabled=True)
    result = await publisher.publish("image.jpg", "caption")
    assert result.success is False
    assert "Disabled" in (result.error or "")


@pytest.mark.asyncio
async def test_email_publisher_sends_and_confirms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    smtp = _DummySMTP()
    monkeypatch.setattr("publisher_v2.services.publishers.email.smtplib.SMTP", lambda *args, **kwargs: smtp)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("publisher_v2.services.publishers.email.asyncio.to_thread", fake_to_thread)

    image_path = tmp_path / "image.jpg"
    with Image.new("RGB", (10, 10), color="red") as img:
        img.save(image_path)

    config = EmailConfig(
        sender="sender@example.com",
        recipient="upload@example.com",
        password="pwd",
        smtp_server="smtp.example.com",
        caption_target="both",
        subject_mode="private",
        confirmation_to_sender=True,
        confirmation_tags_count=1,
    )
    publisher = EmailPublisher(config=config, enabled=True)

    context = {"analysis_tags": [" #Happy ", "#Happy", "Mo0dy!!!"], "alt_text": "A person standing by a window."}
    result = await publisher.publish(str(image_path), "Hello World", context=context)

    assert result.success is True
    assert smtp.starttls_called is True
    assert len(smtp.sent_messages) == 2
    assert smtp.sent_messages[1][1] == ("sender@example.com",)  # fallback when no admin emails
    # Parse the message and decode the subject header (handles RFC 2047 encoding for emojis)
    first_msg = email.message_from_string(smtp.sent_messages[0][2])
    first_subject_raw = first_msg["Subject"]
    decoded_parts = decode_header(first_subject_raw)
    first_subject = "".join(
        part.decode(enc or "utf-8") if isinstance(part, bytes) else part for part, enc in decoded_parts
    )
    assert "Private: Hello World" in first_subject
    confirm_raw = smtp.sent_messages[1][2]
    confirm_msg = email.message_from_string(confirm_raw)
    confirm_body = confirm_msg.get_payload(0).get_payload(decode=True).decode()  # type: ignore[union-attr]
    assert "Image Tags (FetLife context): happy" in confirm_body


@pytest.mark.asyncio
async def test_email_publisher_confirmation_uses_admin_login_emails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    smtp = _DummySMTP()
    monkeypatch.setattr("publisher_v2.services.publishers.email.smtplib.SMTP", lambda *args, **kwargs: smtp)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("publisher_v2.services.publishers.email.asyncio.to_thread", fake_to_thread)

    image_path = tmp_path / "image.jpg"
    with Image.new("RGB", (10, 10), color="red") as img:
        img.save(image_path)

    config = EmailConfig(
        sender="smtp@example.com",
        recipient="upload@example.com",
        password="pwd",
        smtp_server="smtp.example.com",
        confirmation_to_sender=True,
    )
    publisher = EmailPublisher(
        config=config,
        enabled=True,
        admin_login_emails=["  A@Example.com ", "a@example.com", "c@other.com"],
    )

    result = await publisher.publish(str(image_path), "Hi")

    assert result.success is True
    assert len(smtp.sent_messages) == 2
    assert smtp.sent_messages[1][1] == ("A@Example.com", "c@other.com")  # deduped case-insensitively


@pytest.mark.asyncio
async def test_email_publisher_handles_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    smtp = _DummySMTP()
    smtp.fail = True
    monkeypatch.setattr("publisher_v2.services.publishers.email.smtplib.SMTP", lambda *args, **kwargs: smtp)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("publisher_v2.services.publishers.email.asyncio.to_thread", fake_to_thread)

    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"imagedata")

    config = EmailConfig(
        sender="sender@example.com",
        recipient="upload@example.com",
        password="pwd",
        smtp_server="smtp.example.com",
        caption_target="subject",
        subject_mode="normal",
        confirmation_to_sender=False,
    )
    publisher = EmailPublisher(config=config, enabled=True)

    result = await publisher.publish(str(image_path), "Caption")
    assert result.success is False
    assert "failure" in (result.error or "")


class _FakeInstagramClient:
    def __init__(self, *, fail_session: bool = False, fail_upload: bool = False) -> None:
        self.fail_session = fail_session
        self.fail_upload = fail_upload
        self.login_calls: list[tuple[str, str]] = []
        self.settings_saved = False
        self.delay_range: list = []

    def set_settings(self, settings: dict) -> None:
        if self.fail_session:
            raise RuntimeError("bad session")

    def get_settings(self) -> dict:
        self.settings_saved = True
        return {"device_settings": {"model": "test"}}

    def login(self, user: str, pwd: str) -> None:
        self.login_calls.append((user, pwd))

    def photo_upload(self, processed_path: str, caption: str):
        if self.fail_upload:
            raise RuntimeError("upload fail")
        return SimpleNamespace(id=f"{processed_path}:{caption}")


@pytest.mark.asyncio
async def test_instagram_publisher_handles_session_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # #94: a fresh publisher with no stored session logs in once and persists
    # the settings afterwards (dump_settings/get_timeline_feed are gone).
    client = _FakeInstagramClient(fail_session=False, fail_upload=False)
    monkeypatch.setattr("publisher_v2.services.publishers.instagram.Client", lambda: client)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("publisher_v2.services.publishers.instagram.asyncio.to_thread", fake_to_thread)

    from publisher_v2.services.instagram_session import FileSessionStore

    config = InstagramConfig(username="user", password="pass", session_file=str(tmp_path / "session.json"))
    publisher = InstagramPublisher(
        config=config, enabled=True, session_store=FileSessionStore(str(tmp_path / "session.json"))
    )

    result = await publisher.publish(str(tmp_path / "image.jpg"), "caption text")
    assert result.success is True
    assert client.settings_saved is True
    assert (tmp_path / "session.json").exists()
    assert len(client.login_calls) == 1


@pytest.mark.asyncio
async def test_instagram_publisher_returns_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _FakeInstagramClient(fail_session=False, fail_upload=True)
    monkeypatch.setattr("publisher_v2.services.publishers.instagram.Client", lambda: client)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("publisher_v2.services.publishers.instagram.asyncio.to_thread", fake_to_thread)

    from publisher_v2.services.instagram_session import FileSessionStore

    config = InstagramConfig(username="user", password="pass", session_file=str(tmp_path / "session.json"))
    publisher = InstagramPublisher(
        config=config, enabled=True, session_store=FileSessionStore(str(tmp_path / "session.json"))
    )

    result = await publisher.publish(str(tmp_path / "image.jpg"), "caption text")
    assert result.success is False
    assert "upload fail" in (result.error or "")


@pytest.mark.asyncio
async def test_instagram_publisher_disabled_without_config() -> None:
    publisher = InstagramPublisher(config=None, enabled=False)
    result = await publisher.publish("path", "caption")
    assert result.success is False


class _FakeTelegramBot:
    def __init__(self, *_args, **_kwargs) -> None:
        self.sent: tuple[str, str] | None = None
        self.shutdown_called = False
        self.fail = False

    async def send_photo(self, chat_id: str, photo, caption: str):
        if self.fail:
            raise RuntimeError("send fail")
        self.sent = (chat_id, caption)

        class Message:
            message_id = 123

        return Message()

    async def shutdown(self) -> None:
        self.shutdown_called = True


@pytest.mark.asyncio
async def test_telegram_publisher_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bot = _FakeTelegramBot()
    monkeypatch.setattr("publisher_v2.services.publishers.telegram.telegram.Bot", lambda token: bot)

    config = TelegramConfig(bot_token="token", channel_id="channel")
    publisher = TelegramPublisher(config=config, enabled=True)

    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"img")

    result = await publisher.publish(str(image_path), "caption", context={"alt_text": "A person standing by a window."})
    assert result.success is True
    assert bot.sent == ("channel", "caption")
    assert bot.shutdown_called is True


@pytest.mark.asyncio
async def test_telegram_publisher_handles_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bot = _FakeTelegramBot()
    bot.fail = True
    monkeypatch.setattr("publisher_v2.services.publishers.telegram.telegram.Bot", lambda token: bot)

    config = TelegramConfig(bot_token="token", channel_id="channel")
    publisher = TelegramPublisher(config=config, enabled=True)

    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"img")

    result = await publisher.publish(str(image_path), "caption")
    assert result.success is False
    assert bot.shutdown_called is True


# ---------------------------------------------------------------------------
# #94 (REL-9): persistent sessions, one login, explicit challenge handling
# ---------------------------------------------------------------------------


class _SessionFakeClient:
    login_calls = 0  # class-level counter across instances

    def __init__(self) -> None:
        self.delay_range: list = []
        self._settings: dict = {}

    def set_settings(self, settings: dict) -> None:
        self._settings = dict(settings)

    def get_settings(self) -> dict:
        return dict(self._settings) or {"device_settings": {"model": "test"}, "uuids": {"x": "1"}}

    def login(self, username: str, password: str) -> None:
        type(self).login_calls += 1

    def photo_upload(self, path: str, caption: str):
        return SimpleNamespace(id="media-1")


@pytest.mark.asyncio
async def test_instagram_one_login_across_two_publishes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from publisher_v2.services.instagram_session import FileSessionStore

    _SessionFakeClient.login_calls = 0
    monkeypatch.setattr("publisher_v2.services.publishers.instagram.Client", _SessionFakeClient)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("publisher_v2.services.publishers.instagram.asyncio.to_thread", fake_to_thread)

    config = InstagramConfig(username="user", password="pass", session_file=str(tmp_path / "session.json"))
    store = FileSessionStore(str(tmp_path / "session.json"))
    publisher = InstagramPublisher(config=config, enabled=True, session_store=store)

    image = tmp_path / "img.jpg"
    image.write_bytes(b"img")

    first = await publisher.publish(str(image), "caption one")
    second = await publisher.publish(str(image), "caption two")

    assert first.success and second.success
    assert _SessionFakeClient.login_calls == 1
    # Session persisted after login/upload.
    assert (tmp_path / "session.json").exists()


@pytest.mark.asyncio
async def test_instagram_challenge_fails_and_backs_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from instagrapi.exceptions import ChallengeRequired

    from publisher_v2.services.instagram_session import FileSessionStore

    class _ChallengingClient(_SessionFakeClient):
        def login(self, username: str, password: str) -> None:
            type(self).login_calls += 1
            raise ChallengeRequired("challenge_required")

    _ChallengingClient.login_calls = 0
    monkeypatch.setattr("publisher_v2.services.publishers.instagram.Client", _ChallengingClient)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("publisher_v2.services.publishers.instagram.asyncio.to_thread", fake_to_thread)

    config = InstagramConfig(username="user", password="pass", session_file=str(tmp_path / "session.json"))
    store = FileSessionStore(str(tmp_path / "session.json"))
    publisher = InstagramPublisher(config=config, enabled=True, session_store=store)

    image = tmp_path / "img.jpg"
    image.write_bytes(b"img")

    first = await publisher.publish(str(image), "caption")
    assert first.success is False
    assert "challenge" in (first.error or "").lower()
    assert _ChallengingClient.login_calls == 1

    # Backoff active: the second publish never attempts a password login.
    second = await publisher.publish(str(image), "caption")
    assert second.success is False
    assert _ChallengingClient.login_calls == 1


# --- #133: an expired session relogs once instead of a 24h loop ---------------
#
# Fake instagrapi Client with the real library's session semantics: restoring
# settings sets a user id, and login() is then a no-op unless relogin=True
# (instagrapi/mixins/auth.py). The session store is the real FileSessionStore.


class _SessionAwareClient:
    """Stateful fake of instagrapi.Client; ``world`` is shared across Client() instances."""

    def __init__(self, world: dict) -> None:
        self._world = world
        self.user_id: str | None = None
        self.delay_range: list = []
        world["clients"].append(self)

    def set_settings(self, settings: dict) -> None:
        self.user_id = settings.get("user_id")
        self._world["restored"].append(settings)

    def set_uuids(self, uuids: dict) -> None:
        self._world.setdefault("device_carried", []).append(("uuids", uuids))

    def set_device(self, device: dict) -> None:
        self._world.setdefault("device_carried", []).append(("device", device))

    def set_user_agent(self, user_agent: str = "") -> None:
        self._world.setdefault("device_carried", []).append(("user_agent", user_agent))

    def get_settings(self) -> dict:
        return {"user_id": self.user_id, "session": self._world["session"]}

    def login(self, username: str, password: str, relogin: bool = False) -> bool:
        if self.user_id and not relogin:
            return True  # instagrapi: stored user id -> no auth at all
        self._world["password_logins"].append({"relogin": relogin})
        if self._world.get("login_raises"):
            raise self._world["login_raises"]
        self._world["session"] = "fresh"
        self.user_id = "42"
        return True

    def get_timeline_feed(self):
        # instagrapi private_request: a dead session answers 403 login_required.
        if self._world["session"] != "fresh" and self._world.get("feed_detects_expiry", True):
            raise LoginRequired("login_required")
        return {}

    def photo_upload(self, path: str, caption: str):
        if self._world.get("upload_raises_after_relogin") and self._world["session"] == "fresh":
            raise self._world["upload_raises_after_relogin"]
        if self._world["session"] != "fresh":
            # Real instagrapi: rupload rejects a dead session with PhotoNotUpload;
            # configure (private_request) raises LoginRequired.
            if self._world.get("upload_error") == "rupload":
                raise PhotoNotUpload("upload failed")
            raise LoginRequired("login_required")
        return SimpleNamespace(id="media-1")


class _SpyStore:
    """Real FileSessionStore, recording clear() calls."""

    def __init__(self, path: Path) -> None:
        from publisher_v2.services.instagram_session import FileSessionStore

        self._inner = FileSessionStore(str(path))
        self.cleared: list[str] = []

    async def load(self, tenant):
        return await self._inner.load(tenant)

    async def save(self, tenant, settings):
        await self._inner.save(tenant, settings)

    async def get_blocked_until(self, tenant):
        return await self._inner.get_blocked_until(tenant)

    async def set_blocked_until(self, tenant, until):
        return await self._inner.set_blocked_until(tenant, until)

    async def clear(self, tenant):
        self.cleared.append(tenant)
        await self._inner.clear(tenant)


def _expired_session_setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, login_raises=None, **world_flags):
    world: dict = {"clients": [], "restored": [], "password_logins": [], "session": "expired", **world_flags}
    if login_raises is not None:
        world["login_raises"] = login_raises
    monkeypatch.setattr("publisher_v2.services.publishers.instagram.Client", lambda: _SessionAwareClient(world))
    store = _SpyStore(tmp_path / "session.json")
    image = tmp_path / "img.jpg"
    Image.new("RGB", (10, 10)).save(image)
    publisher = InstagramPublisher(
        InstagramConfig(username="user", password="pass", session_file=str(tmp_path / "session.json")),
        True,
        session_store=store,  # type: ignore[arg-type]
    )
    return world, store, publisher, image


async def test_instagram_expired_session_relogs_once_and_publishes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Session check passes (flaky endpoint); expiry surfaces at configure as LoginRequired.
    world, store, publisher, image = _expired_session_setup(monkeypatch, tmp_path, feed_detects_expiry=False)
    await store.save("default", {"user_id": "42", "session": "expired"})

    result = await publisher.publish(str(image), "caption")

    assert result.success is True, result.error
    assert store.cleared == ["default"]
    assert world["password_logins"] == [{"relogin": True}]
    # The relogin used a fresh Client, not the one holding the stale settings.
    assert len(world["clients"]) == 2
    assert world["restored"] == [{"user_id": "42", "session": "expired"}]
    assert await store.get_blocked_until("default") is None
    assert await store.load("default") == {"user_id": "42", "session": "fresh"}


async def test_instagram_relogin_challenge_backs_off_24h_without_looping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world, store, publisher, image = _expired_session_setup(
        monkeypatch, tmp_path, login_raises=ChallengeRequired("challenge_required")
    )
    await store.save("default", {"user_id": "42", "session": "expired"})

    result = await publisher.publish(str(image), "caption")

    assert result.success is False
    assert "ChallengeRequired" in (result.error or "")
    assert len(world["password_logins"]) == 1, "never loop password logins into a challenge"
    assert await store.get_blocked_until("default") is not None
    # A second publish inside the window does not touch Instagram at all.
    again = await publisher.publish(str(image), "caption")
    assert again.success is False and "backoff" in (again.error or "")
    assert len(world["password_logins"]) == 1


async def test_instagram_first_login_challenge_still_backs_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    world, store, publisher, image = _expired_session_setup(
        monkeypatch, tmp_path, login_raises=ChallengeRequired("challenge_required")
    )
    result = await publisher.publish(str(image), "caption")
    assert result.success is False
    assert store.cleared == []
    assert len(world["password_logins"]) == 1
    assert await store.get_blocked_until("default") is not None


async def test_file_session_store_clear_removes_settings(tmp_path: Path) -> None:
    from publisher_v2.services.instagram_session import FileSessionStore

    store = FileSessionStore(str(tmp_path / "s.json"))
    await store.save("t", {"user_id": "1"})
    await store.clear("t")
    assert await store.load("t") is None


def test_standalone_instagram_session_defaults_under_xdg_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Real env-first loader: no session_file override -> the store lives under $XDG_CACHE_HOME."""
    import json as _json

    from publisher_v2.config.loader import load_application_config
    from publisher_v2.services.instagram_session import FileSessionStore

    monkeypatch.setattr("publisher_v2.config.loader.load_dotenv", lambda *a, **k: None)
    for key, value in {
        "STORAGE_PATHS": _json.dumps({"root": "/Photos"}),
        "PUBLISHERS": _json.dumps([{"type": "instagram", "username": "user"}]),
        "INSTA_PASSWORD": "pass",
        "OPENAI_SETTINGS": "{}",
        "OPENAI_API_KEY": "sk-test",
        "DROPBOX_APP_KEY": "k",
        "DROPBOX_APP_SECRET": "s",
        "DROPBOX_REFRESH_TOKEN": "r",
        "XDG_CACHE_HOME": str(tmp_path / "xdg"),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # The DB session factory is a module global; pin "no DB" so run order cannot matter.
    monkeypatch.setattr("publisher_v2.db.get_session_factory", lambda: None)

    cfg = load_application_config()
    assert cfg.instagram is not None
    publisher = InstagramPublisher(cfg.instagram, True)
    assert isinstance(publisher._store, FileSessionStore)
    assert str(publisher._store._path).startswith(str(tmp_path / "xdg"))


async def test_db_session_store_clear_drops_settings_but_keeps_backoff() -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from publisher_v2.db.models import Base
    from publisher_v2.services.instagram_session import DbSessionStore

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    store = DbSessionStore(async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession), "secret")
    try:
        await store.save("t", {"user_id": "1"})
        until = datetime.now(UTC) + timedelta(hours=1)
        await store.set_blocked_until("t", until)
        await store.clear("t")
        assert await store.load("t") is None
        assert await store.get_blocked_until("t") is not None
    finally:
        await engine.dispose()


async def test_instagram_expired_session_caught_by_session_check_before_rupload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Real instagrapi fails a dead session at rupload with PhotoNotUpload; the pre-upload check must catch it."""
    world, store, publisher, image = _expired_session_setup(monkeypatch, tmp_path, upload_error="rupload")
    await store.save("default", {"user_id": "42", "session": "expired"})

    result = await publisher.publish(str(image), "caption")

    assert result.success is True, result.error
    assert store.cleared == ["default"]
    assert world["password_logins"] == [{"relogin": True}]
    assert await store.get_blocked_until("default") is None


@pytest.mark.parametrize(
    "relogin_error",
    [
        ChallengeUnknownStep("challenge"),
        TwoFactorRequired("2fa"),
        BadPassword("ip blacklisted"),
        EOFError("challenge code prompt"),
    ],
    ids=["challenge_subclass", "two_factor", "bad_password", "prompt_eof"],
)
async def test_any_relogin_failure_backs_off_and_never_loops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, relogin_error: BaseException
) -> None:
    world, store, publisher, image = _expired_session_setup(monkeypatch, tmp_path, login_raises=relogin_error)
    await store.save("default", {"user_id": "42", "session": "expired"})

    first = await publisher.publish(str(image), "caption")
    second = await publisher.publish(str(image), "caption")

    assert first.success is False and second.success is False
    assert len(world["password_logins"]) == 1, "a failed relogin must back off, not retry every publish"
    assert await store.get_blocked_until("default") is not None
    assert "backoff" in (second.error or "")


def test_client_surfaces_challenges_instead_of_prompting(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """instagrapi auto-resolves challenges and asks input() for a code unless told otherwise.

    Routed through the real ``private_request`` of a real Client; only the HTTP send is stubbed.
    """
    from instagrapi import Client

    publisher = InstagramPublisher(
        InstagramConfig(username="user", password="pass", session_file=str(tmp_path / "s.json")), True
    )
    client = publisher._get_client()
    assert isinstance(client, Client)
    resolved: list = []

    def _send(*_args, **_kwargs):
        client.last_json = {"message": "challenge_required"}
        raise ChallengeRequired("challenge_required")

    monkeypatch.setattr(client, "_send_private_request", _send)
    monkeypatch.setattr(client, "challenge_resolve", lambda *a, **k: resolved.append(a))
    with pytest.raises(ChallengeRequired):
        client.get_timeline_feed()
    assert resolved == [], "challenge must surface, not be auto-resolved"
    with pytest.raises(ChallengeRequired):
        client.challenge_code_handler("user", 1)


async def test_legacy_relative_session_file_is_picked_up(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """#133 moved the default to XDG; an existing ./instasession.json must not force a fresh password login."""
    import json as _json

    from publisher_v2.services.instagram_session import FileSessionStore

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    (tmp_path / "instasession.json").write_text(_json.dumps({"user_id": "7"}))
    store = FileSessionStore(None)
    assert await store.load("default") == {"user_id": "7"}
    assert (tmp_path / "xdg" / "publisher_v2" / "instagram_session.json").exists()


async def test_clear_does_not_resurrect_legacy_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import json as _json

    from publisher_v2.services.instagram_session import FileSessionStore

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    (tmp_path / "instasession.json").write_text(_json.dumps({"user_id": "7"}))
    store = FileSessionStore(None)
    await store.clear("default")
    assert await store.load("default") is None


async def test_upload_error_after_successful_relogin_does_not_back_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A transient, non-auth upload failure after a working relogin fails once — no 24h block."""
    world, store, publisher, image = _expired_session_setup(
        monkeypatch, tmp_path, upload_raises_after_relogin=PhotoNotUpload("network blip")
    )
    await store.save("default", {"user_id": "42", "session": "expired"})

    result = await publisher.publish(str(image), "caption")

    assert result.success is False
    assert world["password_logins"] == [{"relogin": True}]
    assert await store.get_blocked_until("default") is None
    assert await store.load("default") == {"user_id": "42", "session": "fresh"}


async def test_corrupt_xdg_file_does_not_resurrect_legacy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import json as _json

    from publisher_v2.services.instagram_session import FileSessionStore

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    (tmp_path / "instasession.json").write_text(_json.dumps({"user_id": "old"}))
    xdg = tmp_path / "xdg" / "publisher_v2" / "instagram_session.json"
    xdg.parent.mkdir(parents=True)
    xdg.write_text("{not json")
    assert await FileSessionStore(None).load("default") is None


async def test_fresh_password_login_failure_backs_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No stored session + BadPassword/throttle: back off, never a password login on every publish."""
    world, store, publisher, image = _expired_session_setup(monkeypatch, tmp_path, login_raises=BadPassword("x"))
    first = await publisher.publish(str(image), "caption")
    second = await publisher.publish(str(image), "caption")
    assert first.success is False and second.success is False
    assert len(world["password_logins"]) == 1
    assert await store.get_blocked_until("default") is not None


async def test_cancelled_relogin_leaves_a_backoff(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The workflow's wait_for can cancel mid-relogin; the cleared session must not leave us unprotected."""
    import asyncio as _asyncio

    world, store, publisher, image = _expired_session_setup(
        monkeypatch, tmp_path, login_raises=_asyncio.CancelledError()
    )
    await store.save("default", {"user_id": "42", "session": "expired"})
    with pytest.raises(_asyncio.CancelledError):
        await publisher.publish(str(image), "caption")
    assert await store.get_blocked_until("default") is not None


async def test_relogin_keeps_the_device_fingerprint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    world, store, publisher, image = _expired_session_setup(monkeypatch, tmp_path)
    stale = {
        "user_id": "42",
        "session": "expired",
        "uuids": {"phone_id": "p-1", "uuid": "u-1"},
        "device_settings": {"model": "pixel"},
    }
    await store.save("default", stale)
    result = await publisher.publish(str(image), "caption")
    assert result.success is True, result.error
    assert ("uuids", stale["uuids"]) in world["device_carried"]
    assert ("device", stale["device_settings"]) in world["device_carried"]


async def test_legacy_file_removed_after_migration_and_new_file_private(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import json as _json
    import stat

    from publisher_v2.services.instagram_session import FileSessionStore

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    (tmp_path / "instasession.json").write_text(_json.dumps({"user_id": "7"}))
    assert await FileSessionStore(None).load("default") == {"user_id": "7"}
    assert not (tmp_path / "instasession.json").exists(), "plaintext legacy cookies must not linger"
    new_file = tmp_path / "xdg" / "publisher_v2" / "instagram_session.json"
    assert stat.S_IMODE(new_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(new_file.parent.stat().st_mode) == 0o700


async def test_password_login_skipped_when_backoff_cannot_be_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fail closed: if the pre-login block cannot be stored, do not risk a password login."""
    world, store, publisher, image = _expired_session_setup(monkeypatch, tmp_path)

    async def _broken(tenant, until):
        return False

    monkeypatch.setattr(store, "set_blocked_until", _broken)
    result = await publisher.publish(str(image), "caption")
    assert result.success is False
    assert world["password_logins"] == []


async def test_settings_without_session_identity_use_guarded_password_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A partial/imported settings file (no user id) makes login() a real password login: it must be guarded."""
    world, store, publisher, image = _expired_session_setup(monkeypatch, tmp_path, login_raises=BadPassword("x"))
    await store.save("default", {"uuids": {"phone_id": "p"}})
    await publisher.publish(str(image), "caption")
    await publisher.publish(str(image), "caption")
    assert len(world["password_logins"]) == 1
    assert await store.get_blocked_until("default") is not None


def test_carried_device_recomputes_user_agent_on_a_real_client() -> None:
    """set_device alone leaves instagrapi's default User-Agent; the carry-over must keep them consistent."""
    from instagrapi import Client

    from publisher_v2.services.publishers.instagram import _carry_device

    donor = Client(settings={})
    donor.set_device({**donor.device_settings, "model": "Pixel 7", "manufacturer": "Google"})
    donor.set_user_agent()
    stale = donor.get_settings()

    fresh = Client(settings={})
    assert "Pixel 7" not in fresh.user_agent
    _carry_device(fresh, stale)
    assert fresh.get_settings()["uuids"] == stale["uuids"]
    assert fresh.user_agent == stale["user_agent"]
    assert "Pixel 7" in fresh.user_agent


async def test_a_failed_relogin_keeps_the_device_fingerprint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """#133 review: clearing before the relogin loses the device when the relogin fails.

    `_relogin` cleared the store, then attempted a password login. A transient
    failure there — a connection error, throttling, or the publish timeout
    cancelling the task — left nothing stored. After the 24h block the next
    publish logs in from a brand-new device, which is precisely what triggers
    the challenge this issue exists to avoid.
    """
    world, store, publisher, image = _expired_session_setup(
        monkeypatch, tmp_path, login_raises=ClientConnectionError("network blip")
    )
    stale = {
        "user_id": "42",
        "session": "expired",
        "uuids": {"phone_id": "p-1", "uuid": "u-1"},
        "device_settings": {"model": "pixel"},
        "user_agent": "Instagram 1.2.3 Android",
    }
    await store.save("default", stale)

    result = await publisher.publish(str(image), "caption")

    assert result.success is False
    surviving = await store.load("default") or {}
    assert surviving.get("uuids") == stale["uuids"], "device uuids were lost with the dead session"
    assert surviving.get("device_settings") == stale["device_settings"], "device settings were lost"
    assert surviving.get("user_agent") == stale["user_agent"]
    # The dead credentials must NOT survive — that is what clearing is for.
    assert "session" not in surviving
    assert surviving.get("user_id") in (None, ""), "the dead session identity was kept"


@pytest.mark.parametrize(
    ("exc", "expect_long_block"),
    [
        (ChallengeRequired("challenge"), True),
        (TwoFactorRequired("2fa"), True),
        (BadPassword("wrong"), True),
        (ClientConnectionError("network blip"), False),
    ],
)
async def test_only_a_real_instagram_refusal_costs_a_full_day(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, exc: Exception, expect_long_block: bool
) -> None:
    """#133 review: a 24h lockout for a network error is a large blast radius.

    The issue asked for a back-off on Challenge/2FA. A failed password login
    must still never repeat on every publish, so a transient failure is still
    blocked — just for long enough to stop a loop, not for a day.
    """
    from datetime import UTC, datetime

    from publisher_v2.services.instagram_session import CHALLENGE_BACKOFF_HOURS, TRANSIENT_BACKOFF_HOURS

    world, store, publisher, image = _expired_session_setup(monkeypatch, tmp_path, login_raises=exc)
    await store.save("default", {"user_id": "42", "session": "expired"})

    result = await publisher.publish(str(image), "caption")
    assert result.success is False

    blocked_until = await store.get_blocked_until("default")
    assert blocked_until is not None, "a failed password login must always leave a block"
    hours = (blocked_until - datetime.now(UTC)).total_seconds() / 3600
    expected = CHALLENGE_BACKOFF_HOURS if expect_long_block else TRANSIENT_BACKOFF_HOURS
    assert expected - 0.5 <= hours <= expected + 0.5, f"{type(exc).__name__} blocked for {hours:.1f}h"


async def test_carried_device_keeps_the_full_request_context_on_a_real_client() -> None:
    """#133 review: uuids and device settings alone are not the whole fingerprint.

    `country`, `country_code`, `locale`, `timezone_offset` and `mid` are sent as
    `X-IG-App-Startup-Country`, the three locale headers, `X-IG-Timezone-Offset`
    and `X-MID`. Resetting them to instagrapi's US/en_US defaults while carrying
    a UA whose locale segment says otherwise is device discontinuity — exactly
    what carrying the device is meant to prevent.
    """
    from instagrapi import Client

    from publisher_v2.services.publishers.instagram import _carry_device, _device_fingerprint

    original = Client(settings={})
    # Deliberately divergent: set_locale ends by calling set_country with the
    # locale's own region, so a consistent pair (DE + de_DE) would pass even if
    # set_country were dropped from _carry_device entirely.
    original.set_locale("en_US")
    original.set_country("DE")
    original.set_country_code(49)
    original.set_timezone_offset(0)  # UTC: falsy, and was silently dropped
    original.mid = "mid-token"
    stale = dict(original.get_settings())
    stale["mid"] = "mid-token"

    fresh = Client(settings={})
    _carry_device(fresh, _device_fingerprint(stale))

    assert fresh.country == "DE", "set_locale's implicit set_country overwrote the stored country"
    assert fresh.country_code == 49
    assert fresh.locale == "en_US"
    assert fresh.timezone_offset == 0, "a UTC offset was dropped as falsy"
    assert fresh.mid == "mid-token"
    assert fresh.get_settings()["uuids"] == stale["uuids"]
    assert fresh.get_settings()["device_settings"] == stale["device_settings"]
    assert fresh.get_settings()["user_agent"] == stale["user_agent"]


@pytest.mark.parametrize(
    "exc",
    [
        PleaseWaitFewMinutes("slow down"),
        RateLimitError("rate limited"),
        # HTTP 429. A direct ClientError, not a PrivateError, so no tuple built
        # from the message-driven throttling types can catch it — and it is the
        # likeliest throttling signal, since it fires on the status code.
        ClientThrottledError("429"),
        FeedbackRequired("action blocked"),
        SentryBlock("anti-automation block"),
        ProxyAddressIsBlocked("ip blacklisted"),
        CaptchaChallengeRequired("captcha"),
        BadCredentials("bad credentials"),
    ],
    ids=[
        "please_wait",
        "rate_limited",
        "http_429",
        "feedback_required",
        "sentry_block",
        "proxy_blocked",
        "captcha",
        "bad_credentials",
    ],
)
async def test_only_a_failure_with_no_verdict_gets_the_short_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, exc: Exception
) -> None:
    """#133 review: a 1h block on throttling means ~24 password logins a day.

    Password logins against an already-throttled or blocked account are what
    escalates to a challenge, so classifying any of these as transient could
    manufacture the failure this issue exists to prevent. The classification is
    therefore an allow-list of transient errors, not a list of verdicts: an
    exception nobody has classified costs a day, not 24 logins.
    """
    from datetime import UTC, datetime

    from publisher_v2.services.instagram_session import CHALLENGE_BACKOFF_HOURS

    world, store, publisher, image = _expired_session_setup(monkeypatch, tmp_path, login_raises=exc)
    await store.save("default", {"user_id": "42", "session": "expired"})

    assert (await publisher.publish(str(image), "caption")).success is False

    blocked_until = await store.get_blocked_until("default")
    assert blocked_until is not None
    hours = (blocked_until - datetime.now(UTC)).total_seconds() / 3600
    assert hours >= CHALLENGE_BACKOFF_HOURS - 0.5, f"{type(exc).__name__} only blocked for {hours:.1f}h"


async def test_a_failed_login_drops_the_client_it_was_using(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """#133 review: `asyncio.to_thread` cannot be cancelled.

    After a publish timeout the worker keeps running `client.login(...)` on the
    object `self._client` still points at, so the next publish would touch the
    same `requests.Session` the orphan may still be writing.
    """
    world, store, publisher, image = _expired_session_setup(
        monkeypatch, tmp_path, login_raises=ClientConnectionError("network blip")
    )
    await store.save("default", {"user_id": "42", "session": "expired"})

    assert (await publisher.publish(str(image), "caption")).success is False

    assert publisher._client is None, "the client used by a failed login was kept"
    assert publisher._logged_in is False


async def test_a_symlinked_legacy_session_file_is_never_read_as_a_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """#133 security review: `.resolve()` follows symlinks.

    Anything able to write the process working directory could point
    `./instasession.json` at another file and have the migration read it as a
    session, then copy it into the XDG store.

    Only the read needs guarding: `os.unlink` removes the directory entry and
    never follows a link, so `clear()` was never an arbitrary-file-delete. The
    assertion below that the target survives would pass with or without the
    guard, so it is kept only as a statement of that fact, not as proof.
    """
    import json as _json

    from publisher_v2.services.instagram_session import FileSessionStore

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    victim = tmp_path / "victim.json"
    victim.write_text(_json.dumps({"user_id": "stolen"}))
    (tmp_path / "instasession.json").symlink_to(victim)

    store = FileSessionStore(None)

    assert await store.load("default") is None, "a symlinked legacy file was read as a session"
    await store.clear("default")
    assert victim.exists(), "clear() followed the symlink and deleted the target"


async def test_a_backoff_that_cannot_be_written_is_escalated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog
) -> None:
    """#133 security review: `_back_off` ignored the fail-closed signal.

    `set_blocked_until` returns False when the block could not be stored.
    `_password_login` checks it and refuses to log in, but the session-reuse
    path reaches `_back_off` without a password login — there the publish
    failed and nothing was recorded, so the next publish retries immediately:
    a narrower version of the loop #133 removes.
    """
    import logging as _logging

    # A live session whose upload is challenged: no password login happens, so
    # the fail-closed check in _password_login is never consulted.
    world, store, publisher, image = _expired_session_setup(
        monkeypatch, tmp_path, upload_raises_after_relogin=ChallengeRequired("challenge")
    )
    await store.save("default", {"user_id": "42", "session": "fresh"})
    world["session"] = "fresh"

    async def _refuse(tenant, until):
        return False

    monkeypatch.setattr(store, "set_blocked_until", _refuse)

    with caplog.at_level(_logging.ERROR, logger="publisher_v2.publishers.instagram"):
        assert (await publisher.publish(str(image), "caption")).success is False

    assert world["password_logins"] == [], "this path must not attempt a password login"
    assert "instagram_backoff_not_stored" in caplog.text


async def test_a_fingerprint_without_a_stored_user_agent_derives_one_from_its_device() -> None:
    """#133 review: hoisting `set_user_agent` out of the device branch dropped this.

    A fingerprint can hold device settings but no UA. Skipping the call leaves
    the UA instagrapi derived at construction from its DEFAULT device, so the
    UA and the device settings describe different phones — worse than either
    consistently. Passing `""` makes instagrapi derive it from the device just
    carried.
    """
    from instagrapi import Client

    from publisher_v2.services.publishers.instagram import _carry_device

    donor = Client(settings={})
    # Start from the real default shape so every key the UA template needs is
    # present, then change the phone it describes.
    device = dict(donor.device_settings)
    device.update({"manufacturer": "Google", "model": "Pixel 7"})
    donor.set_device(device)
    fingerprint = {"device_settings": device, "uuids": donor.get_settings()["uuids"]}
    assert "user_agent" not in fingerprint

    fresh = Client(settings={})
    _carry_device(fresh, fingerprint)

    assert "Pixel 7" in fresh.user_agent, fresh.user_agent
    assert "Google" in fresh.user_agent, fresh.user_agent


async def test_a_truncated_device_settings_does_not_cost_a_day() -> None:
    """#133 review: `set_user_agent("")` renders a template from device_settings.

    A stored session with an incomplete device dict cannot fill that template,
    and the resulting KeyError lands in the verdict arm of `_password_login` —
    so a malformed store would block for 24h and never even attempt the login,
    repeating on every publish. A mismatched UA is survivable; this is not.
    """
    from instagrapi import Client

    from publisher_v2.services.publishers.instagram import _carry_device

    fresh = Client(settings={})

    _carry_device(fresh, {"device_settings": {"model": "pixel"}})

    assert fresh.device_settings["model"] == "pixel"


async def test_email_subject_folds_line_breaks_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """#147: a multi-line caption killed the send (a header cannot hold a newline).

    Folding on *all* whitespace would also collapse runs of spaces and rewrite
    tabs, U+00A0 and the CJK ideographic space in subjects that were going out
    verbatim before, so only the line breaks are folded.
    """
    import email as email_mod
    from email.header import decode_header, make_header

    smtp = _DummySMTP()
    monkeypatch.setattr("publisher_v2.services.publishers.email.smtplib.SMTP", lambda *args, **kwargs: smtp)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("publisher_v2.services.publishers.email.asyncio.to_thread", fake_to_thread)

    image_path = tmp_path / "image.jpg"
    with Image.new("RGB", (10, 10), color="red") as img:
        img.save(image_path)

    config = EmailConfig(
        sender="sender@example.com",
        recipient="upload@example.com",
        password="pwd",
        smtp_server="smtp.example.com",
        caption_target="subject",
        subject_mode="normal",
        confirmation_to_sender=False,
    )
    publisher = EmailPublisher(config=config, enabled=True)
    caption = "Tokyo　Night  and\ttabs\nsecond line"

    result = await publisher.publish(str(image_path), caption)

    assert result.success is True, result.error
    parsed = email_mod.message_from_string(smtp.sent_messages[0][2])
    subject = str(make_header(decode_header(parsed["Subject"])))
    assert "\n" not in subject and "\r" not in subject, "a header cannot hold a line break"
    assert subject == "Tokyo　Night  and\ttabs second line", subject
