from __future__ import annotations

import asyncio
import logging
from typing import Optional

from instagrapi import Client

from publisher_v2.config.schema import InstagramConfig
from publisher_v2.config.static_loader import get_static_config
from publisher_v2.core.models import PublishResult
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.utils.images import ensure_max_width_async
from publisher_v2.utils.logging import log_publisher_publish, now_monotonic


logger = logging.getLogger("publisher_v2.publishers.instagram")


class InstagramPublisher(Publisher):
    def __init__(self, config: Optional[InstagramConfig], enabled: bool):
        self._config = config
        self._enabled = enabled and config is not None
        self._limits = get_static_config().service_limits.instagram

    @property
    def platform_name(self) -> str:
        return "instagram"

    def is_enabled(self) -> bool:
        return self._enabled

    async def publish(self, image_path: str, caption: str, context: Optional[dict] = None) -> PublishResult:
        if not self._enabled or not self._config:
            return PublishResult(success=False, platform=self.platform_name, error="Disabled or not configured")

        start = now_monotonic()
        try:
            processed_path = await ensure_max_width_async(image_path, max_width=1080)

            def _upload() -> str:
                client = Client()
                client.delay_range = [
                    self._limits.delay_min_seconds,
                    self._limits.delay_max_seconds,
                ]
                # Try session-based login first
                try:
                    client.load_settings(self._config.session_file)
                    client.login(self._config.username, self._config.password)
                    client.get_timeline_feed()
                except Exception:
                    # Fallback to fresh login and persist new session
                    client.login(self._config.username, self._config.password)
                    client.dump_settings(self._config.session_file)
                media = client.photo_upload(processed_path, caption)
                return str(media.id) if hasattr(media, "id") else ""

            post_id = await asyncio.to_thread(_upload)
            log_publisher_publish(logger, self.platform_name, start, success=True)
            return PublishResult(success=True, platform=self.platform_name, post_id=post_id or None)
        except Exception as exc:
            log_publisher_publish(logger, self.platform_name, start, success=False, error=str(exc))
            return PublishResult(success=False, platform=self.platform_name, error=str(exc))


