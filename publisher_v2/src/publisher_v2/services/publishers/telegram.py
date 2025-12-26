from __future__ import annotations

import logging
from typing import Optional

import telegram

from publisher_v2.config.schema import TelegramConfig
from publisher_v2.core.models import PublishResult
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.utils.images import ensure_max_width_async
from publisher_v2.utils.logging import log_publisher_publish, now_monotonic


logger = logging.getLogger("publisher_v2.publishers.telegram")


class TelegramPublisher(Publisher):
    def __init__(self, config: Optional[TelegramConfig], enabled: bool):
        self._config = config
        self._enabled = (
            enabled
            and config is not None
            and bool(getattr(config, "bot_token", None))
            and bool(getattr(config, "channel_id", None))
        )

    @property
    def platform_name(self) -> str:
        return "telegram"

    def is_enabled(self) -> bool:
        return self._enabled

    async def publish(self, image_path: str, caption: str, context: Optional[dict] = None) -> PublishResult:
        if not self._enabled or not self._config:
            return PublishResult(success=False, platform=self.platform_name, error="Disabled or not configured")

        bot = telegram.Bot(token=self._config.bot_token)
        start = now_monotonic()
        try:
            processed_path = await ensure_max_width_async(image_path, max_width=1280)
            with open(processed_path, "rb") as f:
                message = await bot.send_photo(chat_id=self._config.channel_id, photo=f, caption=caption)
            log_publisher_publish(logger, self.platform_name, start, success=True)
            return PublishResult(success=True, platform=self.platform_name, post_id=str(message.message_id))
        except Exception as exc:
            log_publisher_publish(logger, self.platform_name, start, success=False, error=str(exc))
            return PublishResult(success=False, platform=self.platform_name, error=str(exc))
        finally:
            # Properly close the bot client to avoid ResourceWarning
            await bot.shutdown()

