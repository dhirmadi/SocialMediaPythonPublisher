"""#97 stage 3: wire previously-dead email/SMTP config.

- ``SMTPLimits.timeout_seconds`` (static config) drives the SMTP socket
  timeout; the hard-coded 30 becomes the fallback.
- ``EmailConfig.use_tls`` controls STARTTLS (orchestrator
  ``email_server.use_tls``).
- ``EmailConfig.smtp_username`` overrides the login user (orchestrator
  ``email_server.username``); sender remains the fallback.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from publisher_v2.config.schema import EmailConfig
from publisher_v2.services.publishers.email import EmailPublisher


class _DummySMTP:
    def __init__(self) -> None:
        self.init_kwargs: dict = {}
        self.starttls_called = False
        self.login_args: tuple[str, str] | None = None
        self.sent: list[tuple] = []

    def __enter__(self) -> _DummySMTP:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        pass

    def starttls(self) -> None:
        self.starttls_called = True

    def login(self, user: str, pwd: str) -> None:
        self.login_args = (user, pwd)

    def sendmail(self, sender, recipients, message) -> None:
        self.sent.append((sender, tuple(recipients), message))


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> _DummySMTP:
    dummy = _DummySMTP()

    def _factory(*args, **kwargs):
        dummy.init_kwargs = kwargs
        return dummy

    monkeypatch.setattr("publisher_v2.services.publishers.email.smtplib.SMTP", _factory)
    return dummy


@pytest.fixture
def image(tmp_path: Path) -> str:
    from PIL import Image

    p = tmp_path / "img.jpg"
    Image.new("RGB", (2, 2), color=(120, 40, 40)).save(p, format="JPEG")
    return str(p)


def _config(**overrides) -> EmailConfig:
    base = dict(
        sender="sender@example.com",
        recipient="to@example.com",
        password="pw",
        smtp_server="smtp.example.com",
        smtp_port=587,
        confirmation_to_sender=False,
    )
    base.update(overrides)
    return EmailConfig(**base)


async def test_smtp_timeout_from_static_config(smtp: _DummySMTP, image: str, monkeypatch) -> None:
    """AC: SMTPLimits.timeout_seconds is honored instead of the hard-coded 30."""
    from publisher_v2.config.static_loader import get_static_config

    static = get_static_config()
    monkeypatch.setattr(static.service_limits.smtp, "timeout_seconds", 12.5)

    publisher = EmailPublisher(config=_config(), enabled=True)
    result = await publisher.publish(image, "caption")
    assert result.success is True
    assert smtp.init_kwargs.get("timeout") == 12.5


async def test_smtp_timeout_defaults_to_30_when_unset(smtp: _DummySMTP, image: str, monkeypatch) -> None:
    from publisher_v2.config.static_loader import get_static_config

    static = get_static_config()
    monkeypatch.setattr(static.service_limits.smtp, "timeout_seconds", None)

    publisher = EmailPublisher(config=_config(), enabled=True)
    result = await publisher.publish(image, "caption")
    assert result.success is True
    assert smtp.init_kwargs.get("timeout") == 30


async def test_use_tls_true_calls_starttls(smtp: _DummySMTP, image: str) -> None:
    publisher = EmailPublisher(config=_config(use_tls=True), enabled=True)
    result = await publisher.publish(image, "caption")
    assert result.success is True
    assert smtp.starttls_called is True


async def test_use_tls_false_skips_starttls(smtp: _DummySMTP, image: str) -> None:
    publisher = EmailPublisher(config=_config(use_tls=False), enabled=True)
    result = await publisher.publish(image, "caption")
    assert result.success is True
    assert smtp.starttls_called is False


async def test_use_tls_defaults_true(smtp: _DummySMTP, image: str) -> None:
    """Backward compat: default config keeps STARTTLS on."""
    publisher = EmailPublisher(config=_config(), enabled=True)
    result = await publisher.publish(image, "caption")
    assert result.success is True
    assert smtp.starttls_called is True


async def test_smtp_username_used_for_login(smtp: _DummySMTP, image: str) -> None:
    publisher = EmailPublisher(config=_config(smtp_username="relay-user"), enabled=True)
    result = await publisher.publish(image, "caption")
    assert result.success is True
    assert smtp.login_args == ("relay-user", "pw")


async def test_login_falls_back_to_sender(smtp: _DummySMTP, image: str) -> None:
    publisher = EmailPublisher(config=_config(), enabled=True)
    result = await publisher.publish(image, "caption")
    assert result.success is True
    assert smtp.login_args == ("sender@example.com", "pw")


def test_orchestrator_email_server_fields_mapped() -> None:
    """source.py maps email_server.use_tls / username into EmailConfig."""
    from publisher_v2.config.orchestrator_models import OrchestratorEmailServer

    server = OrchestratorEmailServer(
        host="smtp.example.com",
        port=2525,
        use_tls=False,
        from_email="from@example.com",
        username="relay-user",
        password_ref="ref-1",
    )
    assert server.use_tls is False
    assert server.username == "relay-user"
