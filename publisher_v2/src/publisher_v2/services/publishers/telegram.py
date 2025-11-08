from __future__ import annotations

import asyncio
from typing import Optional

import telegram

from publisher_v2.config.schema import TelegramConfig
from publisher_v2.core.models import PublishResult
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.utils.images import ensure_max_width


class TelegramPublisher(Publisher):
    def __init__(self, config: Optional[TelegramConfig], enabled: bool):
        self._config = config
        self._enabled = enabled and config is not None

    @property
    def platform_name(self) -> str:
        return "telegram"

    def is_enabled(self) -> bool:
        return self._enabled

    async def publish(self, image_path: str, caption: str) -> PublishResult:
        if not self._enabled or not self._config:
            return PublishResult(success=False, platform=self.platform_name, error="Disabled or not configured")
        try:
            processed_path = ensure_max_width(image_path, max_width=1280)
            bot = telegram.Bot(token=self._config.bot_token)
            with open(processed_path, "rb") as f:
                message = await bot.send_photo(chat_id=self._config.channel_id, photo=f, caption=caption)
            return PublishResult(success=True, platform=self.platform_name, post_id=str(message.message_id))
        except Exception as exc:
            return PublishResult(success=False, platform=self.platform_name, error=str(exc))


