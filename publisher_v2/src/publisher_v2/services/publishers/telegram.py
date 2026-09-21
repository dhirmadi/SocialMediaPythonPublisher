"""Telegram publisher: posts the image with its caption to a configured channel.

Uses python-telegram-bot's async ``send_photo``. Failures never raise — they
are sanitised (the bot token can appear in SDK error strings) and returned as
an unsuccessful ``PublishResult``.
"""

import logging

import telegram

from publisher_v2.config.schema import TelegramConfig
from publisher_v2.core.models import PublishResult
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.utils.logging import log_publisher_publish, now_monotonic

logger = logging.getLogger("publisher_v2.publishers.telegram")


class TelegramPublisher(Publisher):
    """Publisher that sends photos to a Telegram channel via a bot."""

    def __init__(self, config: TelegramConfig | None, enabled: bool):
        """Configure the publisher and decide up front whether it can publish.

        The publisher only counts as enabled when ``enabled`` is set and the
        config actually carries both a bot token and a channel id, so a
        half-filled config disables it rather than failing at publish time.

        Args:
            config: Telegram bot token and channel id; None when unconfigured.
            enabled: Whether Telegram is switched on for this tenant.
        """
        self._config = config
        self._enabled = enabled and config is not None and bool(config.bot_token) and bool(config.channel_id)

    @property
    def platform_name(self) -> str:
        """Return the platform identifier used in results and log records."""
        return "telegram"

    def is_enabled(self) -> bool:
        """Return True when a bot token and channel id were both configured."""
        return self._enabled

    async def publish(self, image_path: str, caption: str, context: dict | None = None) -> PublishResult:
        """Send the local image with ``caption`` to the configured channel.

        Never raises: a disabled publisher, a missing token or any SDK error
        comes back as ``PublishResult(success=False)`` with a sanitised message,
        so one platform's failure cannot abort the run. On success the Telegram
        message id is returned as ``post_id``. The bot client is always shut
        down afterwards.

        Args:
            image_path: Path to the already-downloaded image on local disk.
            caption: Caption text to attach to the photo.
            context: Unused; present for the Publisher interface.
        """
        if not self._enabled or not self._config:
            return PublishResult(success=False, platform=self.platform_name, error="Disabled or not configured")

        token = self._config.bot_token
        if not token:
            return PublishResult(success=False, platform=self.platform_name, error="bot_token not configured")
        bot = telegram.Bot(token=token)
        start = now_monotonic()
        try:
            with open(image_path, "rb") as f:  # noqa: ASYNC230 — file handle needed by async send_photo
                message = await bot.send_photo(chat_id=self._config.channel_id, photo=f, caption=caption)
            log_publisher_publish(logger, self.platform_name, start, success=True)
            return PublishResult(success=True, platform=self.platform_name, post_id=str(message.message_id))
        except Exception as exc:
            from publisher_v2.services.publishers._sanitize import sanitize_publisher_error

            safe = sanitize_publisher_error(exc)
            log_publisher_publish(logger, self.platform_name, start, success=False, error=safe)
            return PublishResult(success=False, platform=self.platform_name, error=safe)
        finally:
            # Properly close the bot client to avoid ResourceWarning
            await bot.shutdown()
