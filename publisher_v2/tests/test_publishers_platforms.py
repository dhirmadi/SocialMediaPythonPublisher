from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from publisher_v2.config.schema import EmailConfig, InstagramConfig, TelegramConfig
from publisher_v2.services.publishers.email import EmailPublisher
from publisher_v2.services.publishers.instagram import InstagramPublisher
from publisher_v2.services.publishers.telegram import TelegramPublisher


class _DummySMTP:
    def __init__(self, *_args, **_kwargs) -> None:
        self.starttls_called = False
        self.login_args = None
        self.sent_messages: list[tuple[str, tuple[str, ...], str]] = []
        self.closed = False
        self.fail = False

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

    context = {"analysis_tags": [" #Happy ", "#Happy", "Mo0dy!!!"]}
    result = await publisher.publish(str(image_path), "Hello World", context=context)

    assert result.success is True
    assert smtp.starttls_called is True
    assert len(smtp.sent_messages) == 2
    first_subject = [line for line in smtp.sent_messages[0][2].split("\n") if line.startswith("Subject")][0]
    assert "Private: Hello World" in first_subject
    confirm_body = smtp.sent_messages[1][2]
    assert "Image Tags (FetLife context): happy" in confirm_body


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
        self.dumped = False

    def load_settings(self, _path: str) -> None:
        if self.fail_session:
            raise RuntimeError("bad session")

    def login(self, user: str, pwd: str) -> None:
        self.login_calls.append((user, pwd))

    def get_timeline_feed(self) -> None:
        if self.fail_session:
            raise RuntimeError("timeline fail")

    def dump_settings(self, _path: str) -> None:
        self.dumped = True

    def photo_upload(self, processed_path: str, caption: str):
        if self.fail_upload:
            raise RuntimeError("upload fail")
        return SimpleNamespace(id=f"{processed_path}:{caption}")


@pytest.mark.asyncio
async def test_instagram_publisher_handles_session_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def fake_resize(path: str, max_width: int) -> str:
        return path

    monkeypatch.setattr("publisher_v2.services.publishers.instagram.ensure_max_width_async", fake_resize)

    client = _FakeInstagramClient(fail_session=True, fail_upload=False)
    monkeypatch.setattr("publisher_v2.services.publishers.instagram.Client", lambda: client)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("publisher_v2.services.publishers.instagram.asyncio.to_thread", fake_to_thread)

    config = InstagramConfig(username="user", password="pass", session_file=str(tmp_path / "session.json"))
    publisher = InstagramPublisher(config=config, enabled=True)

    result = await publisher.publish(str(tmp_path / "image.jpg"), "caption text")
    assert result.success is True
    assert client.dumped is True
    assert len(client.login_calls) >= 1


@pytest.mark.asyncio
async def test_instagram_publisher_returns_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def fake_resize(path: str, max_width: int) -> str:
        return path

    monkeypatch.setattr("publisher_v2.services.publishers.instagram.ensure_max_width_async", fake_resize)

    client = _FakeInstagramClient(fail_session=False, fail_upload=True)
    monkeypatch.setattr("publisher_v2.services.publishers.instagram.Client", lambda: client)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("publisher_v2.services.publishers.instagram.asyncio.to_thread", fake_to_thread)

    config = InstagramConfig(username="user", password="pass", session_file=str(tmp_path / "session.json"))
    publisher = InstagramPublisher(config=config, enabled=True)

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
        self.sent = None
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
    async def fake_resize(path: str, max_width: int) -> str:
        return path

    monkeypatch.setattr("publisher_v2.services.publishers.telegram.ensure_max_width_async", fake_resize)
    bot = _FakeTelegramBot()
    monkeypatch.setattr("publisher_v2.services.publishers.telegram.telegram.Bot", lambda token: bot)

    config = TelegramConfig(bot_token="token", channel_id="channel")
    publisher = TelegramPublisher(config=config, enabled=True)

    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"img")

    result = await publisher.publish(str(image_path), "caption")
    assert result.success is True
    assert bot.sent == ("channel", "caption")
    assert bot.shutdown_called is True


@pytest.mark.asyncio
async def test_telegram_publisher_handles_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def fake_resize(path: str, max_width: int) -> str:
        return path

    monkeypatch.setattr("publisher_v2.services.publishers.telegram.ensure_max_width_async", fake_resize)
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


